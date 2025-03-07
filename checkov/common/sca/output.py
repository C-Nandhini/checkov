from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional, Dict, List

from packaging import version as packaging_version

from checkov.common.bridgecrew.integration_features.features.policy_metadata_integration import (
    integration as metadata_integration,
)
from checkov.common.bridgecrew.platform_integration import bc_integration
from checkov.common.bridgecrew.severities import Severities
from checkov.common.models.enums import CheckResult, ScanDataFormat
from checkov.common.output.extra_resource import ExtraResource
from checkov.common.output.record import Record, DEFAULT_SEVERITY, SCA_PACKAGE_SCAN_CHECK_NAME, SCA_LICENSE_CHECK_NAME
from checkov.common.sca.commons import (
    get_file_path_for_record,
    get_resource_for_record,
    get_package_alias,
    UNFIXABLE_VERSION,
    get_package_type,
    normalize_twistcli_language,
)
from checkov.common.util.http_utils import request_wrapper
from checkov.runner_filter import RunnerFilter
from checkov.common.output.common import format_licenses_to_string

if TYPE_CHECKING:
    from checkov.common.output.common import SCADetails
    from checkov.common.output.report import Report
    from checkov.common.typing import _LicenseStatus, _CheckResult


def create_report_license_record(
        rootless_file_path: str,
        file_abs_path: str,
        check_class: str,
        licenses_status: _LicenseStatus,
        sca_details: SCADetails | None = None,
) -> Record:
    package_name = licenses_status["package_name"]
    package_version = licenses_status["package_version"]
    policy = licenses_status["policy"]
    bc_status = licenses_status["status"]

    # renaming the status name from the one in platform's report to be convenient with checkov's-report
    status = "FAILED" if bc_status == "OPEN" else bc_status

    check_result: _CheckResult = {
        "result": CheckResult.FAILED,
    }
    if status == "COMPLIANT":
        check_result["result"] = CheckResult.PASSED

    code_block = [(0, f"{package_name}: {package_version}")]

    details = {
        "package_name": package_name,
        "package_version": package_version,
        "license": licenses_status["license"],
        "status": status,
        "policy": policy,
        "package_type": get_package_type(package_name, package_version, sca_details),
    }

    record = Record(
        check_id=policy,
        bc_check_id=policy,
        check_name=SCA_LICENSE_CHECK_NAME,
        check_result=check_result,
        code_block=code_block,
        file_path=get_file_path_for_record(rootless_file_path),
        file_line_range=[0, 0],
        resource=get_resource_for_record(rootless_file_path, package_name),
        check_class=check_class,
        evaluations=None,
        file_abs_path=file_abs_path,
        vulnerability_details=details,
    )
    return record


def _update_details_by_scan_data_format(
        details: dict[str, Any],
        vulnerability_details: dict[str, Any],
        sca_details: SCADetails | None = None,
        scan_data_format: ScanDataFormat = ScanDataFormat.TWISTCLI
) -> None:
    if scan_data_format in {ScanDataFormat.TWISTCLI, ScanDataFormat.DEPENDENCY_TREE}:
        lowest_fixed_version = UNFIXABLE_VERSION
        package_version = vulnerability_details["packageVersion"]
        fixed_versions: list[packaging_version.Version | packaging_version.LegacyVersion] = []
        status = vulnerability_details.get("status") or "open"
        if status != "open":
            parsed_current_version = packaging_version.parse(package_version)
            for version in status.replace("fixed in", "").split(","):
                parsed_version = packaging_version.parse(version.strip())
                if parsed_version > parsed_current_version:
                    fixed_versions.append(parsed_version)

            if fixed_versions:
                lowest_fixed_version = str(min(fixed_versions))
        details.update({"status": status, "lowest_fixed_version": lowest_fixed_version,
                        "fixed_versions": fixed_versions, "image_details": sca_details})
    elif scan_data_format == ScanDataFormat.PLATFORM:
        status = vulnerability_details["status"]
        fix_version = vulnerability_details.get("cveStatus")
        details.update({"status": status, "fix_version": fix_version})


def create_report_cve_record(
        rootless_file_path: str,
        file_abs_path: str,
        check_class: str,
        vulnerability_details: dict[str, Any],
        licenses: str,
        root_package_version: str | None = None,
        root_package_name: str | None = None,
        runner_filter: RunnerFilter | None = None,
        sca_details: SCADetails | None = None,
        scan_data_format: ScanDataFormat = ScanDataFormat.TWISTCLI,
) -> Record:
    runner_filter = runner_filter or RunnerFilter()
    package_name = vulnerability_details["packageName"]
    package_version = vulnerability_details["packageVersion"]
    package_type = get_package_type(package_name, package_version, sca_details)
    cve_id = vulnerability_details.get("id", vulnerability_details.get("cveId", '')).upper()
    severity = vulnerability_details.get("severity", DEFAULT_SEVERITY)
    # sanitize severity names
    if severity == "moderate":
        severity = "medium"
    description = vulnerability_details.get("description")

    check_result: _CheckResult = {
        "result": CheckResult.FAILED,
    }

    if runner_filter.skip_cve_package and package_name in runner_filter.skip_cve_package:
        check_result = {
            "result": CheckResult.SKIPPED,
            "suppress_comment": f"Filtered by package '{package_name}'",
        }
    elif not runner_filter.within_threshold(Severities[severity.upper()]):
        check_result = {
            "result": CheckResult.SKIPPED,
            "suppress_comment": "Filtered by severity",
        }

    code_block = [(0, f"{package_name}: {package_version}")]

    details = {
        "id": cve_id,
        "severity": severity,
        "package_name": package_name,
        "package_version": package_version,
        "package_type": package_type,
        "link": vulnerability_details.get("link"),
        "cvss": vulnerability_details.get("cvss"),
        "vector": vulnerability_details.get("vector"),
        "description": description,
        "risk_factors": vulnerability_details.get("riskFactors"),
        "published_date": vulnerability_details.get("publishedDate") or (datetime.now() - timedelta(
            days=vulnerability_details.get("publishedDays", 0))).isoformat(),
        "licenses": licenses,
        "root_package_name": root_package_name,
        "root_package_version": root_package_version
    }
    _update_details_by_scan_data_format(details, vulnerability_details, sca_details, scan_data_format)

    record = Record(
        check_id=f"CKV_{cve_id.replace('-', '_')}",
        bc_check_id=f"BC_{cve_id.replace('-', '_')}",
        check_name=SCA_PACKAGE_SCAN_CHECK_NAME,
        check_result=check_result,
        code_block=code_block,
        file_path=get_file_path_for_record(rootless_file_path),
        file_line_range=[0, 0],
        resource=get_resource_for_record(rootless_file_path, package_name),
        check_class=check_class,
        evaluations=None,
        file_abs_path=file_abs_path,
        severity=Severities[severity.upper()],
        description=description,
        short_description=f"{cve_id} - {package_name}: {package_version}",
        vulnerability_details=details,
    )
    return record


def _add_to_report_licenses_statuses(
        report: Report,
        check_class: str | None,
        scanned_file_path: str,
        rootless_file_path: str,
        runner_filter: RunnerFilter,
        license_statuses: list[_LicenseStatus],
        sca_details: SCADetails | None = None,
        report_type: str | None = None,
) -> dict[str, list[str]]:
    licenses_per_package_map: dict[str, list[str]] = defaultdict(list)

    for license_status in license_statuses:
        # filling 'licenses_per_package_map', will be used in the call to 'create_report_cve_record' for efficient
        # extracting of license per package
        package_name, package_version, license = (
            license_status["package_name"],
            license_status["package_version"],
            license_status["license"],
        )
        licenses_per_package_map[get_package_alias(package_name, package_version)].append(license)

        policy = license_status["policy"]

        license_record = create_report_license_record(
            rootless_file_path=rootless_file_path,
            file_abs_path=scanned_file_path,
            check_class=check_class or "",
            licenses_status=license_status,
            sca_details=sca_details,
        )

        if not runner_filter.should_run_check(
                check_id=policy,
                bc_check_id=policy,
                severity=metadata_integration.get_severity(policy),
                report_type=report_type,
        ):
            if runner_filter.checks:
                continue
            else:
                license_record.check_result = {
                    "result": CheckResult.SKIPPED,
                    "suppress_comment": f"{policy} is skipped",
                }

        report.add_resource(license_record.resource)
        report.add_record(license_record)

    return licenses_per_package_map


def add_to_reports_cves_and_packages(
        report: Report,
        check_class: str | None,
        scanned_file_path: str,
        rootless_file_path: str,
        runner_filter: RunnerFilter,
        vulnerabilities: list[dict[str, Any]],
        packages: list[dict[str, Any]],
        licenses_per_package_map: dict[str, list[str]],
        sca_details: SCADetails | None = None,
        report_type: str | None = None,
        scan_data_format: ScanDataFormat = ScanDataFormat.TWISTCLI,
) -> None:
    vulnerable_packages = []

    for vulnerability in vulnerabilities:
        package_name, package_version = vulnerability["packageName"], vulnerability["packageVersion"]
        cve_record = create_report_cve_record(
            rootless_file_path=rootless_file_path,
            file_abs_path=scanned_file_path,
            check_class=check_class or "",
            vulnerability_details=vulnerability,
            licenses=format_licenses_to_string(
                licenses_per_package_map[get_package_alias(package_name, package_version)]),
            runner_filter=runner_filter,
            sca_details=sca_details,
            scan_data_format=scan_data_format,
        )
        if not runner_filter.should_run_check(
                check_id=cve_record.check_id,
                bc_check_id=cve_record.bc_check_id,
                severity=cve_record.severity,
                report_type=report_type,
        ):
            if runner_filter.checks:
                continue
            else:
                cve_record.check_result = {
                    "result": CheckResult.SKIPPED,
                    "suppress_comment": f"{vulnerability['id']} is skipped",
                }

        report.add_resource(cve_record.resource)
        report.add_record(cve_record)
        vulnerable_packages.append(get_package_alias(package_name, package_version))

    for package in packages:
        if get_package_alias(package["name"], package["version"]) not in vulnerable_packages:
            # adding resources without cves for adding them also in the output-bom-repors
            report.extra_resources.add(
                ExtraResource(
                    file_abs_path=scanned_file_path,
                    file_path=get_file_path_for_record(rootless_file_path),
                    resource=get_resource_for_record(rootless_file_path, package["name"]),
                    vulnerability_details={
                        "package_name": package["name"],
                        "package_version": package["version"],
                        "licenses": format_licenses_to_string(
                            licenses_per_package_map[get_package_alias(package["name"], package["version"])]),
                        "package_type": get_package_type(package["name"], package["version"], sca_details),
                    },
                )
            )


def add_to_reports_cves_and_packages_with_dependencies(
        report: Report,
        check_class: str | None,
        scanned_file_path: str,
        rootless_file_path: str,
        runner_filter: RunnerFilter,
        vulnerabilities: list[dict[str, Any]],
        packages: list[dict[str, Any]],
        licenses_per_package_map: dict[str, list[str]],
        dependencies: dict[str, List[int]] | None,
        sca_details: SCADetails | None = None,
        report_type: str | None = None,
        scan_data_format: ScanDataFormat = ScanDataFormat.TWISTCLI,
) -> None:
    vulnerable_packages: dict[str, list[dict[str, Any]]] = {}
    root_packages_list: list[int] = []

    create_vulnerable_packages_dict(vulnerable_packages, vulnerabilities)

    for package in packages:
        package_name, package_version = package["name"], package["version"]
        package_alias = get_package_alias(package_name, package_version)

        create_root_packages_list(root_packages_list, packages, package, dependencies)

        if package_alias in vulnerable_packages:
            package["cves"] = vulnerable_packages[package_alias]
        else:
            package["cves"] = []
            # adding resources without cves for adding them also in the output-bom-repors
            add_extra_resources_to_report(report, scanned_file_path, rootless_file_path,
                                          package_name, package_version, package_alias,
                                          licenses_per_package_map, sca_details)

    for root_package_index in root_packages_list:
        vulnerable_dependencies: list[dict[str, Any]] = []
        if dependencies:
            find_vulnerable_dependencies(vulnerable_dependencies, dependencies, root_package_index, packages)

        root_package = packages[root_package_index]
        if len(root_package["cves"]) > 0 or len(vulnerable_dependencies) > 0:
            root_package["vulnerable_dependencies"] = vulnerable_dependencies

        for cve in root_package["cves"]:
            add_cve_record_to_report(vulnerability_details=cve, package=root_package,
                                     rootless_file_path=rootless_file_path, scanned_file_path=scanned_file_path,
                                     check_class=check_class, licenses_per_package_map=licenses_per_package_map,
                                     runner_filter=runner_filter, sca_details=sca_details,
                                     scan_data_format=scan_data_format, report_type=report_type, report=report,
                                     root_package_version=root_package["version"],
                                     root_package_name=root_package["name"])

        for dep in root_package.get("vulnerable_dependencies", []):
            for dep_cve in dep["cves"]:
                add_cve_record_to_report(vulnerability_details=dep_cve, package=dep,
                                         rootless_file_path=rootless_file_path, scanned_file_path=scanned_file_path,
                                         check_class=check_class, licenses_per_package_map=licenses_per_package_map,
                                         runner_filter=runner_filter, sca_details=sca_details,
                                         scan_data_format=scan_data_format, report_type=report_type, report=report,
                                         root_package_version=root_package["version"],
                                         root_package_name=root_package["name"])


def add_cve_record_to_report(vulnerability_details: dict[str, Any], package: dict[str, Any], rootless_file_path: str,
                             scanned_file_path: str, check_class: Optional[str],
                             licenses_per_package_map: dict[str, list[str]], runner_filter: RunnerFilter,
                             sca_details: Optional[SCADetails], scan_data_format: ScanDataFormat,
                             report_type: Optional[str], report: Report,
                             root_package_version: str, root_package_name: str) -> None:
    cve_record = create_report_cve_record(
        rootless_file_path=rootless_file_path,
        file_abs_path=scanned_file_path,
        check_class=check_class or "",
        vulnerability_details=vulnerability_details,
        licenses=format_licenses_to_string(
            licenses_per_package_map[get_package_alias(package["name"], package["version"])]),
        runner_filter=runner_filter,
        sca_details=sca_details,
        scan_data_format=scan_data_format,
        root_package_version=root_package_version,
        root_package_name=root_package_name
    )
    if not runner_filter.should_run_check(
            check_id=cve_record.check_id,
            bc_check_id=cve_record.bc_check_id,
            severity=cve_record.severity,
            report_type=report_type,
    ):
        if runner_filter.checks:
            return
        else:
            cve_record.check_result = {
                "result": CheckResult.SKIPPED,
                "suppress_comment": f"{vulnerability_details.get('cveId', vulnerability_details.get('id', ''))} is skipped"}

    report.add_resource(cve_record.resource)
    report.add_record(cve_record)


def find_vulnerable_dependencies(vulnerable_dependencies: list[dict[str, Any]], dependencies: dict[str, list[int]],
                                 root_package_index: int, packages: list[dict[str, Any]]) -> None:
    visited_dependencies: set[int] = set()  # Set to keep track of visited_dependencies nodes.
    dfs(visited=visited_dependencies, graph=dependencies, root=root_package_index)
    if len(visited_dependencies) > 0:
        for package_idx in visited_dependencies:
            package = packages[package_idx]
            if len(package["cves"]) > 0:
                vulnerable_dependencies.append(package)


def create_root_packages_list(root_packages_list: list[int], packages: list[dict[str, Any]], package: dict[str, Any],
                              dependencies: Optional[Dict[str, List[int]]]) -> None:
    if dependencies:
        if package.get("root", ""):
            root_packages_list.append(packages.index(package))
    else:
        # if we don't have dependencies, all packages will be "roots"
        root_packages_list.append(packages.index(package))


def create_vulnerable_packages_dict(vulnerable_packages: dict[str, list[dict[str, Any]]],
                                    vulnerabilities: list[dict[str, Any]]) -> None:
    for vulnerability in vulnerabilities:
        package_alias = get_package_alias(vulnerability["packageName"], vulnerability["packageVersion"])
        if package_alias not in vulnerable_packages:
            vulnerable_packages[package_alias] = []

        vulnerable_packages[package_alias].append(vulnerability)


def add_extra_resources_to_report(report: Report, scanned_file_path: str, rootless_file_path: str,
                                  package_name: str, package_version: str, package_alias: str,
                                  licenses_per_package_map: dict[str, list[str]],
                                  sca_details: Optional[SCADetails]) -> None:
    report.extra_resources.add(
        ExtraResource(
            file_abs_path=scanned_file_path,
            file_path=get_file_path_for_record(rootless_file_path),
            resource=get_resource_for_record(rootless_file_path, package_name),
            vulnerability_details={
                "package_name": package_name,
                "package_version": package_version,
                "licenses": format_licenses_to_string(
                    licenses_per_package_map[package_alias]),
                "package_type": get_package_type(package_name, package_version, sca_details),
            },
        )
    )


def dfs(root: int, visited: set[int], graph: dict[str, list[int]]) -> None:
    root_str = str(root)
    if root_str not in graph:
        return

    for node in graph[root_str]:
        if node not in visited:
            visited.add(node)
            dfs(node, visited, graph)


def add_to_report_sca_data(
        report: Report,
        check_class: str | None,
        scanned_file_path: str,
        rootless_file_path: str,
        runner_filter: RunnerFilter,
        vulnerabilities: list[dict[str, Any]],
        packages: list[dict[str, Any]],
        license_statuses: list[_LicenseStatus],
        dependencies: dict[str, list[int]] | None = None,
        sca_details: SCADetails | None = None,
        report_type: str | None = None,
) -> None:
    licenses_per_package_map: dict[str, list[str]] = \
        _add_to_report_licenses_statuses(report, check_class, scanned_file_path, rootless_file_path, runner_filter,
                                         license_statuses, sca_details, report_type)
    if dependencies is not None:
        # if dependencies is empty list it means we got results via DependencyTree scan but no dependencies have found.
        add_to_reports_cves_and_packages_with_dependencies(report=report, check_class=check_class,
                                                           scanned_file_path=scanned_file_path,
                                                           rootless_file_path=rootless_file_path,
                                                           runner_filter=runner_filter,
                                                           vulnerabilities=vulnerabilities,
                                                           packages=packages,
                                                           licenses_per_package_map=licenses_per_package_map,
                                                           sca_details=sca_details,
                                                           report_type=report_type,
                                                           scan_data_format=ScanDataFormat.DEPENDENCY_TREE,
                                                           dependencies=dependencies)
    else:
        add_to_reports_cves_and_packages(report=report, check_class=check_class, scanned_file_path=scanned_file_path,
                                         rootless_file_path=rootless_file_path, runner_filter=runner_filter,
                                         vulnerabilities=vulnerabilities, packages=packages,
                                         licenses_per_package_map=licenses_per_package_map, sca_details=sca_details,
                                         report_type=report_type,
                                         scan_data_format=ScanDataFormat.TWISTCLI)


def _get_request_input(packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"name": package.get("name", ""), "version": package.get("version", ""),
         "lang": normalize_twistcli_language(package.get("type", ""))}
        for package in packages
    ]


def get_license_statuses(packages: list[dict[str, Any]]) -> list[_LicenseStatus]:
    requests_input = _get_request_input(packages)
    if not requests_input:
        return []
    try:
        response = request_wrapper(
            method="POST",
            url=f"{bc_integration.api_url}/api/v1/vulnerabilities/packages/get-licenses-violations",
            headers=bc_integration.get_default_headers("POST"),
            json={"packages": requests_input},
            should_call_raise_for_status=True
        )
        response_json = response.json()
        license_statuses: list[_LicenseStatus] = [
            {
                "package_name": license_violation.get("name", ""),
                "package_version": license_violation.get("version", ""),
                "policy": license_violation.get("policy", "BC_LIC1"),
                "license": license_violation.get("license", ""),
                "status": license_violation.get("status", "COMPLIANT")
            }
            for license_violation in response_json.get("violations", [])
        ]
        return license_statuses
    except Exception:
        error_message = (
            "failing when trying to get licenses-violations. it is apparently some unexpected "
            "connection issue. please try later. in case it keep happening. please report."
        )
        logging.info(error_message, exc_info=True)

    return []
