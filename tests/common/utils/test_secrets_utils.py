from checkov.common.models.enums import CheckResult
from checkov.common.util.secrets import omit_secret_value_from_checks, omit_secret_value_from_definitions
from checkov.terraform.checks.provider.aws.credentials import AWSCredentials
from checkov.terraform.checks.resource.azure.SecretExpirationDate import SecretExpirationDate


def test_omit_secret_value_from_checks_by_attribute(tfplan_resource_lines_with_secrets,
                                                    tfplan_resource_config_with_secrets,
                                                    tfplan_resource_lines_without_secrets):
    check = SecretExpirationDate()
    check.entity_type = 'azurerm_key_vault_secret'
    check_result = {'result': CheckResult.FAILED}
    resource_attributes_to_omit = {'azurerm_key_vault_secret': 'value'}

    assert omit_secret_value_from_checks(check, check_result, tfplan_resource_lines_with_secrets,
                                         tfplan_resource_config_with_secrets, resource_attributes_to_omit
                                         ) == tfplan_resource_lines_without_secrets


def test_omit_secret_value_from_checks_by_secret(aws_provider_lines_with_secrets, aws_provider_config_with_secrets,
                                                 aws_provider_lines_without_secrets):
    check = AWSCredentials()
    check_result = {'result': CheckResult.FAILED}

    assert omit_secret_value_from_checks(check, check_result, aws_provider_lines_with_secrets,
                                         aws_provider_config_with_secrets
                                         ) == aws_provider_lines_without_secrets


def test_omit_secret_value_from_definitions_by_attribute(tfplan_definitions_with_secrets,
                                                         tfplan_definitions_without_secrets):
    resource_attributes_to_omit = {'azurerm_key_vault_secret': 'value'}
    censored_definitions = omit_secret_value_from_definitions(tfplan_definitions_with_secrets,
                                                              resource_attributes_to_omit)
    assert censored_definitions == tfplan_definitions_without_secrets


def test_omit_secret_value_from_checks_by_secret_2():
    entity_lines_with_secrets = [
        (93, '          "values": {\n'),
        (94, '            "content_type": null,\n'),
        (95, '            "expiration_date": null,\n'),
        (96, '            "key_vault_id": "/subscriptions/my-subscription/resourceGroups/my-rg/providers/Microsoft.KeyVault/vaults/my-vault",\n'),
        (97, '            "name": "my-key-vault",\n'),
        (98, '            "not_before_date": null,\n'),
        (99, '            "tags": null,\n'),
        (100, '            "timeouts": null,\n'),
        (101, '            "value": "-----BEGIN RSA PRIVATE KEY-----\\nMOCKKEYmer0YcjoLJVs4VvyLaigj7ygbpplVefQFHXseE7Lx0S2YBA6cg5SHoe4huMCsLwqyHJane2aseEq6oreSUG4Fzk3XpZSJ8fhNTdH2XHjCiK2LmAMHLV34adw2DEVKESa3PTf86EPIXu77qOH5HMl9tCXl9e1xf3wluaecOjdamK9HcNv8l0R58tTIuHpK+HiT69EHUjn7Igv904vPoTSl3f0Ut+xYTWOBBQJRG9YI7fHLJTL5ki1Hbb6Kl/6rsFur3P32kHQqFtDb9l7AQ/J68ws6MNfi+n5EylyRMgWkDRaryDPfRp9Aoe82Fo0pZDarEmphE58+FTKw5eC6qh3\\n-----END RSA PRIVATE KEY-----\\n"\n')
    ]
    entity_config_with_secrets = {
        'content_type': [None],
        'expiration_date': [None],
        'key_vault_id': ['/subscriptions/my-subscription/resourceGroups/my-rg/providers/Microsoft.KeyVault/vaults/my-vault'],
        'name': ['my-key-vault'], 'not_before_date': [None], 'tags': [None], 'timeouts': [None],
        'value': ['-----BEGIN RSA PRIVATE KEY-----\nMOCKKEYmer0YcjoLJVs4VvyLaigj7ygbpplVefQFHXseE7Lx0S2YBA6cg5SHoe4huMCsLwqyHJane2aseEq6oreSUG4Fzk3XpZSJ8fhNTdH2XHjCiK2LmAMHLV34adw2DEVKESa3PTf86EPIXu77qOH5HMl9tCXl9e1xf3wluaecOjdamK9HcNv8l0R58tTIuHpK+HiT69EHUjn7Igv904vPoTSl3f0Ut+xYTWOBBQJRG9YI7fHLJTL5ki1Hbb6Kl/6rsFur3P32kHQqFtDb9l7AQ/J68ws6MNfi+n5EylyRMgWkDRaryDPfRp9Aoe82Fo0pZDarEmphE58+FTKw5eC6qh3\n-----END RSA PRIVATE KEY-----\n'],
        '__startline__': [93], '__endline__': [102], 'start_line': [92], 'end_line': [101],
        'references_': ['tls_private_key.ssh.private_key_pem', 'tls_private_key.ssh'],
        '__address__': 'azurerm_key_vault_secret.akv_009_pass_01', '__change_actions__': ['create']}
    check = SecretExpirationDate()
    check.entity_type = 'azurerm_key_vault_secret'
    check_result = {'result': CheckResult.FAILED}

    entity_lines_without_secrets = [
        (93, '          "values": {\n'),
        (94, '            "content_type": null,\n'),
        (95, '            "expiration_date": null,\n'),
        (96, '            "key_vault_id": "/subscriptions/my-subscription/resourceGroups/my-rg/providers/Microsoft.KeyVault/vaults/my-vault",\n'),
        (97, '            "name": "my-key-vault",\n'),
        (98, '            "not_before_date": null,\n'),
        (99, '            "tags": null,\n'),
        (100, '            "timeouts": null,\n'),
        (101, '            "value": "-----BEGIN RSA PRIVATE KEY-----\\nMOCKKEY*********************************************************************************************************************************************************************************************************************************************************************************************************************************************************************************--\\n"\n')
    ]
    resource_attributes_to_omit = {'azurerm_key_vault_secret': 'value'}

    result = omit_secret_value_from_checks(check, check_result, entity_lines_with_secrets, entity_config_with_secrets,
                                           resource_attributes_to_omit)

    assert result == entity_lines_without_secrets
