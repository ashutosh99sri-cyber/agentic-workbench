import time

import pytest

from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.secrets import SecretRedactor


def test_structured_sensitive_fields() -> None:
    assert SecretRedactor().clean({"nested": {"password": "unknown-value"}}) == {
        "nested": {"password": "[REDACTED]"}
    }


def test_known_values_and_recognized_keys_are_redacted():
    key = "sk-proj-abcdefghijklmnopqrstuvwxyz123456789"
    redactor = SecretRedactor(values=["private-value"])
    raw = f"credential={key}\nprivate-value\npassword = 'hunter-two'\n"
    assert redactor.contains_secret(raw)
    clean = redactor.redact(raw)
    assert key not in clean and "private-value" not in clean and "hunter-two" not in clean
    assert clean.count("\n") == raw.count("\n")


def test_json_and_multiline_secrets_keep_structure_and_lines():
    secret = "-----BEGIN PRIVATE KEY-----\nabc123\n-----END PRIVATE KEY-----"
    redactor = SecretRedactor(values=[secret])
    clean = redactor.clean({"message": secret, "nested": ["safe", secret]})
    assert clean["message"].count("\n") == secret.count("\n")
    assert "abc123" not in str(clean)


def test_source_citations_hash_original_but_only_redacted_text_is_returned(tmp_path):
    key = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
    (tmp_path / "app.py").write_text(f"TOKEN = '{key}'\nprint('safe')\n")
    source = WorkspacePolicy(tmp_path, redactor=SecretRedactor()).read_source("app.py")
    assert key not in source.text
    assert source.contains_secrets
    assert source.text.count("\n") == 2


@pytest.mark.parametrize(
    ("assignment", "value"),
    [
        ("PASSWORD=plainword\n", "plainword"),
        ("api_key: local-development-key # comment\n", "local-development-key"),
        ("token = abc123;\n", "abc123"),
        ("password=hunter2\n", "hunter2"),
        ("api_key: abcdefgh\n", "abcdefgh"),
        ("token = unquoted-value\n", "unquoted-value"),
        ("api_key: demo_secret_value\n", "demo_secret_value"),
        ("PASSWORD=demo_secret_value\n", "demo_secret_value"),
        ("API_KEY=YWJjZA==\n", "YWJjZA=="),
        ("password=p@$$w0rd\n", "p@$$w0rd"),
        ('password = "hunter-two"\n', "hunter-two"),
        ("{'token': 'quoted-value'}\n", "quoted-value"),
        ("export STRIPE_WEBHOOK_SECRET=whsec_fixture_123\n", "whsec_fixture_123"),
        ("DB_PASSWORD=hunter2\n", "hunter2"),
        ("github-token: unknown-format-value\n", "unknown-format-value"),
    ],
)
def test_named_assignment_literals_are_detected_and_redacted(assignment, value):
    redactor = SecretRedactor()
    assert redactor.contains_secret(assignment)
    cleaned = redactor.redact(assignment)
    assert value not in cleaned
    assert "[REDACTED]" in cleaned
    assert cleaned.count("\n") == assignment.count("\n")


@pytest.mark.parametrize(
    "source",
    [
        "password = config.password\n",
        "api_key = os.environ['API_KEY']\n",
        "token = current_token()\n",
        "secret = get_secret()\n",
        "password = None\n",
        "token: null\n",
        "password = False\n",
        "API_KEY=$API_KEY\n",
        "API_KEY=${API_KEY}\n",
        "password=$(lookup_password)\n",
        "token = config['token']\n",
        "api_key = process.env.API_KEY\n",
        "token: true\n",
        "password == current_password\n",
        "STRIPE_WEBHOOK_SECRET = settings.stripe_webhook_secret\n",
        "DB_PASSWORD=${DB_PASSWORD}\n",
    ],
)
def test_code_references_and_empty_configuration_are_preserved(source):
    redactor = SecretRedactor()
    assert not redactor.contains_secret(source)
    assert redactor.redact(source) == source


@pytest.mark.parametrize(
    "text",
    [
        "a-" * 20_000,
        "ab-c_" * 8_000,
        "secret-" * 6_000,
        "-token" * 6_000,
        "x" * 40_000 + "=v\n",
        "token=" * 8_000 + " x",
        "token=" * 8_000 + "(",
        "_token=a" * 6_000 + " x",
        "A_" * 20_000 + "SECRET=v\n",
        "token=" * 8_000 + " " * 48_000 + "(",
        "token=" * 8_000 + "\t " * 24_000 + "x",
    ],
    ids=[
        "hyphens",
        "mixed",
        "keyword-hyphens",
        "hyphen-keyword",
        "long-name",
        "overlapping-values",
        "overlapping-values-paren",
        "prefixed-overlapping-values",
        "long-prefix",
        "malformed-whitespace-tail",
        "malformed-tab-tail",
    ],
)
def test_secret_name_matching_stays_linear_on_long_separator_runs(text):
    redactor = SecretRedactor()
    started = time.perf_counter()
    redactor.contains_secret(text)
    redactor.redact(text)
    assert time.perf_counter() - started < 2.0


@pytest.mark.parametrize(
    "key",
    [
        "SERVICE_AUTH_TOKEN",
        "stripe-webhook-secret",
        "clientSecret",
        "refreshToken",
        "myAPIKey",
        "AWSSecretAccessKey",
        "aws_secret_access_key",
        "privateKey",
        "DB_PASSWORD",
    ],
)
def test_prefixed_and_camel_case_structured_keys_are_redacted(key):
    assert SecretRedactor().clean({"nested": {key: "synthetic-value"}}) == {
        "nested": {key: "[REDACTED]"}
    }


@pytest.mark.parametrize(
    "key",
    [
        "input_tokens",
        "max_output_tokens",
        "inputTokens",
        "token_type",
        "tokenizer",
        "idempotency_key",
        "sortKey",
        "credentials",
        "key",
    ],
)
def test_non_secret_structured_keys_are_preserved(key):
    assert SecretRedactor().clean({key: "kept"}) == {key: "kept"}


@pytest.mark.parametrize(
    ("assignment", "value"),
    [
        ('clientSecret = "abc123"\n', "abc123"),
        ('"refreshToken": "r-123"\n', "r-123"),
        ("myAPIKey: k-123\n", "k-123"),
        ("AWSSecretAccessKey=wJalrXUtnFEMI\n", "wJalrXUtnFEMI"),
        ("aws_secret_access_key = wJalrXUtnFEMI\n", "wJalrXUtnFEMI"),
        ("PRIVATE_KEY=pk-2\n", "pk-2"),
        ('const githubToken = "ghx-1";\n', "ghx-1"),
    ],
)
def test_camel_case_and_compound_assignments_are_redacted(assignment, value):
    redactor = SecretRedactor()
    assert redactor.contains_secret(assignment)
    assert value not in redactor.redact(assignment)


@pytest.mark.parametrize(
    "source",
    [
        "maxTokens = 100\n",
        "inputTokens: 10\n",
        "tokenCount = 3\n",
        "isSecret = true\n",
        "fetch(url, {credentials: 'include'})\n",
        "cancelToken: source.token\n",
        'inputType = "password"\n',
    ],
)
def test_camel_case_look_alikes_are_preserved(source):
    redactor = SecretRedactor()
    assert not redactor.contains_secret(source)
    assert redactor.redact(source) == source


@pytest.mark.parametrize(
    "name",
    [
        "A" * 64 + "_API_KEY",
        "A" * 65 + "_API_KEY",
        "PART_" * 16 + "SECRET",
        "PART_" * 17 + "SECRET",
    ],
    ids=["64-char-segment", "65-char-segment", "16-segments", "17-segments"],
)
def test_long_prefixed_names_stay_redacted_through_source_reads(tmp_path, name):
    marker = "synthetic-long-prefix-credential"
    (tmp_path / "config.py").write_text(f'{name} = "{marker}"\n')
    source = WorkspacePolicy(tmp_path, redactor=SecretRedactor()).read_source("config.py")
    assert source.contains_secrets and marker not in source.text


@pytest.mark.parametrize(
    "source",
    [
        "class Settings(BaseSettings):\n    database_password: str\n    jwt_secret: str\n",
        "interface Auth {\n  accessToken: string;\n}\n",
        "password: SecretStr\n",
        "self.api_key = api_key\n",
        "DB_PASSWORD = db_password\n",
        "token = access_token\n",
    ],
    ids=["pydantic", "typescript", "secretstr", "self-copy", "case-copy", "variable"],
)
def test_type_annotations_and_identifier_copies_are_not_literals(tmp_path, source):
    redactor = SecretRedactor()
    assert not redactor.contains_secret(source)
    assert redactor.redact(source) == source
    (tmp_path / "settings.py").write_text(source)
    assert (
        not WorkspacePolicy(tmp_path, redactor=redactor).read_source("settings.py").contains_secrets
    )


@pytest.mark.parametrize(
    ("assignment", "value"),
    [
        ("password = s3cr3t-password\n", "s3cr3t-password"),
        ("api_key: str-123\n", "str-123"),
        ("token = my-token\n", "my-token"),
    ],
)
def test_hyphenated_literals_shaped_like_names_stay_redacted(assignment, value):
    assert value not in SecretRedactor().redact(assignment)


@pytest.mark.parametrize(
    ("assignment", "value"),
    [
        ("SECRET_KEY = 'django-insecure-abc'\n", "django-insecure-abc"),
        ("STRIPE_SECRET_KEY=sk_live_123\n", "sk_live_123"),
        ("JWT_SECRET_KEY: xyz-1\n", "xyz-1"),
        ("secret_key_base: abc123\n", "abc123"),
        ('secretKey = "s-1"\n', "s-1"),
    ],
)
def test_secret_key_names_are_redacted(assignment, value):
    redactor = SecretRedactor()
    assert redactor.contains_secret(assignment)
    assert value not in redactor.redact(assignment)


@pytest.mark.parametrize("key", ["SECRET_KEY", "secretKey", "secret_key_base", "STRIPE_SECRET_KEY"])
def test_secret_key_structured_fields_are_redacted(key):
    assert SecretRedactor().clean({key: "v"}) == {key: "[REDACTED]"}


@pytest.mark.parametrize("source", ["secret_key_id = 5\n", "SECRET_KEY = os.environ['SECRET']\n"])
def test_secret_key_look_alikes_are_preserved(source):
    assert SecretRedactor().redact(source) == source


def test_private_key_blocks_are_redacted_and_unterminated_markers_stay_linear():
    redactor = SecretRedactor()
    block = "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----"
    cleaned = redactor.redact(f"key = load()\n{block}\n")
    assert "MIIabc" not in cleaned and cleaned.count("\n") == 4
    started = time.perf_counter()
    redactor.redact("-----BEGIN PRIVATE KEY-----" * 8_000)
    redactor.contains_secret("-----BEGIN PRIVATE KEY-----" * 8_000)
    assert time.perf_counter() - started < 2.0


FIRST_COPY = "MIIEowIBAAKCAQEA1x9fQ2ZbV7kLp3RtYwXe0Hc4nA8sJmUq5vGd2oFiKyTzNrWb"


@pytest.mark.parametrize(
    "source",
    [
        "-----BEGIN RSA PRIVATE KEY-----\nProc-Type: 4,ENCRYPTED\nDEK-Info: AES-128-CBC,3F17F5\n\n"
        f"{FIRST_COPY}\n-----BEGIN RSA PRIVATE KEY-----\nMIIsecond\n"
        "-----END RSA PRIVATE KEY-----\n",
        f"tls:\n  key: |\n    -----BEGIN RSA PRIVATE KEY-----\n    {FIRST_COPY}\n"
        "    -----BEGIN RSA PRIVATE KEY-----\n    MIIsecond\n    -----END RSA PRIVATE KEY-----\n",
        '{"msg": "-----BEGIN PRIVATE KEY-----\\n' + FIRST_COPY + '\\n"}\n'
        '{"msg": "-----BEGIN PRIVATE KEY-----\\nMIIsecond\\n-----END PRIVATE KEY-----\\n"}\n',
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKC\nAQEA1x9fQ2Zb\n"
        "-----BEGIN RSA PRIVATE KEY-----\nMIIsecond\n-----END RSA PRIVATE KEY-----\n",
    ],
    ids=["encrypted-header", "yaml-indented", "json-escaped", "short-wrapped"],
)
def test_a_truncated_key_copy_before_a_complete_block_is_redacted(source):
    redacted = SecretRedactor().redact(source)
    assert "MIIEowIBAAKC" not in redacted and "MIIsecond" not in redacted
    assert redacted.count("\n") == source.count("\n")


def test_configured_values_are_replaced_in_one_pass_with_bounded_growth():
    redactor = SecretRedactor(("RE", "D", "A", "E"))
    assert redactor.redact("RE") == "[REDACTED]"
    text = "DEAR" * 1_000
    assert len(redactor.redact(text)) <= 10 * len(text)


JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwi"
    "aWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
)


@pytest.mark.parametrize(
    ("source", "value"),
    [
        ("      MYSQL_ROOT_PASSWORD: secret\n", "secret"),
        ("      POSTGRES_PASSWORD: password\n", "password"),
        ("spring.datasource.password=SuperSecret\n", "SuperSecret"),
        ("password = TopSecret\n", "TopSecret"),
        ("clientSecret='abc password='hunter2'\n", "hunter2"),
        ("redis:\n  task-queue-redis-password: hunter2\n", "hunter2"),
        ('clientSecret := "9f8e7d6c5b4a"\n', "9f8e7d6c5b4a"),
        ('secret_key: str = "9f8e7d6c5b4a"\n', "9f8e7d6c5b4a"),
        ('const apiKey: string = "9f8e7d6c5b4a";\n', "9f8e7d6c5b4a"),
        ("app.config['SECRET_KEY'] = 'dev-9f8e7d6c'\n", "dev-9f8e7d6c"),
        (f"token = {JWT}\n", JWT),
        ("Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456\n", "abcdefghijklmnopqrstuvwxyz"),
        (
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAtruncatedFirstCopy\n"
            "-----BEGIN RSA PRIVATE KEY-----\nMIIabcdefghijklmnop\n-----END RSA PRIVATE KEY-----\n",
            "MIIEowIBAAKCAQEAtruncatedFirstCopy",
        ),
        ("SERVICE_PASSWORD = 'synthetic example passphrase.'\n", "synthetic example passphrase."),
        ('  db_password: "correct horse battery staple!"\n', "correct horse battery staple!"),
        ('const adminToken = "open sesame, my friend.";\n', "open sesame, my friend."),
        ('NO_REPLY_PASSWORD = "the quick brown fox."\n', "the quick brown fox."),
    ],
    ids=[
        "compose-secret",
        "compose-password",
        "properties-camel",
        "ini",
        "unbalanced-quote",
        "kebab-sk",
        "go-short-declaration",
        "typed-python",
        "typed-typescript",
        "subscript",
        "bare-jwt",
        "bearer-header",
        "truncated-pem",
        "prefixed-passphrase",
        "yaml-passphrase",
        "camel-passphrase",
        "no-reply-passphrase",
    ],
)
def test_credential_forms_are_redacted(source, value):
    redactor = SecretRedactor()
    assert redactor.contains_secret(source)
    assert value not in redactor.redact(source)


@pytest.mark.parametrize(
    "source",
    [
        '{"pageToken": "CAoQAA"}',
        "nextPageToken: CAoQAA\n",
        'no_token: "You can\'t access this page."\n',
        'invalidPassword: "Wrong email or password."\n',
        "errors.expired_token = 'Your session has expired.'\n",
        'DEFAULT_PAD_TOKEN = "[PAD]"\n',
        "SOS_token = 0\n",
        'ENV_API_KEY = "ANTHROPIC_API_KEY"\n',
        'GRANT_TYPE_REFRESH_TOKEN = "refresh_token"\n',
        'POSTGRES_PASSWORD: "${POSTGRES_PASSWORD}"\n',
        'OPENAI_API_KEY: "${{ secrets.OPENAI_API_KEY }}"\n',
        'password: "{{ vault_password }}"\n',
        "self.password = password\n",
        'eos_token: "</s>"\n',
    ],
)
def test_references_cursors_and_messages_are_not_credentials(source):
    redactor = SecretRedactor()
    assert not redactor.contains_secret(source)
    assert redactor.redact(source) == source


def test_message_names_with_long_spaced_values_stay_linear():
    started = time.perf_counter()
    SecretRedactor().redact('no_token: "' + "a " * 40_000 + '"\n')
    assert time.perf_counter() - started < 2.0


def test_structured_secret_containers_are_redacted_and_flags_kept():
    cleaned = SecretRedactor().clean(
        {
            "SecretString": "hunter2",
            "Authorization": "Bearer x",
            "secrets": {"db": "hunter2"},
            "has_password": False,
            "is_secret": True,
            "nextPageToken": "CAoQAA",
            "NextToken": "page-2",
            "eos_token": "</s>",
        }
    )
    assert (
        cleaned["SecretString"] == cleaned["Authorization"] == cleaned["secrets"] == ("[REDACTED]")
    )
    assert cleaned["has_password"] is False and cleaned["is_secret"] is True
    assert cleaned["nextPageToken"] == "CAoQAA" and cleaned["NextToken"] == "page-2"
    assert cleaned["eos_token"] == "</s>"


@pytest.mark.parametrize(
    ("source", "secret"),
    [
        (
            "private_key='-----BEGIN PRIVATE KEY-----'\nMIIEowIBAAKCAQEAbodyAfterQuote\n"
            "-----END PRIVATE KEY-----\n",
            "MIIEowIBAAKCAQEAbodyAfterQuote",
        ),
        (
            "private_key = -----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAinlineBody\n"
            "-----END RSA PRIVATE KEY-----\n",
            "MIIEowIBAAKCAQEAinlineBody",
        ),
        ("token: Bearer abcdefghijklmnopqrstuvwx0123\n", "abcdefghijklmnopqrstuvwx0123"),
    ],
    ids=["quoted-pem-header", "inline-pem", "bearer-value"],
)
def test_assignment_and_pattern_spans_are_merged_on_the_original_text(source, secret):
    redacted = SecretRedactor().redact(source)
    assert secret not in redacted
    assert redacted.count("\n") == source.count("\n")


def test_overlapping_configured_values_are_all_redacted_and_redaction_is_idempotent():
    redactor = SecretRedactor(("xa", "abcdef", "RE", "D", "E"))
    once = redactor.redact("xabcdef and RE then D")
    assert "bcdef" not in once and redactor.redact(once) == once
    assert not redactor.contains_secret(once)
    multiline = SecretRedactor(("\n", "line\n"))
    text = "line\nnext\n" * 100
    assert len(multiline.redact(text)) <= 10 * len(text)
