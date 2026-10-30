# Run the service over https on a dev PC to try the corporate SSO.
#
# The corporate SSO cookie only reaches hosts under the company domain, and
# that domain forces https (HSTS). So:
#   1. hosts file (as admin): 127.0.0.1  dtest-local.<company domain>
#   2. .env:
#        SSO_ADAPTER=company
#        PUBLIC_API_ORIGIN=https://dtest-local.<company domain>:5000
#        FRONTEND_ORIGIN=https://dtest-local.<company domain>:5000
#        SSO_ALLOWED_RETURN_ROOTS=["/", "/dev"]
#        SSO_ALLOWED_ORIGINS=["<origin from the sso_login_url_rejected log>"]
#        COOKIE_SECURE=true
#   3. From the repo root:
#        .\scripts\run_local_https.ps1 -HostName dtest-local.<company domain>
#   4. Open https://<HostName>:<Port>/api/v1/auth/login/sso?return_to=/dev/
#      and accept the certificate warning once.
#
# Runs without gaia (uvicorn directly), since gaia's uvicorn.run takes no
# TLS options. Make a new certificate with -NewCert.

param(
    [Parameter(Mandatory = $true)][string]$HostName,
    [int]$Port = 5000,
    [switch]$NewCert
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$key = Join-Path $root ".local\tls\$HostName-key.pem"
$cert = Join-Path $root ".local\tls\$HostName-cert.pem"
if ($NewCert -or -not (Test-Path $key) -or -not (Test-Path $cert)) {
    uv run --with cryptography python scripts/make_local_cert.py $HostName
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

# internal/gaia keeps the app in src/dtest; main runs src/main.py.
if (Test-Path (Join-Path $root "src\dtest\local.py")) {
    $app = @("src.dtest.local:app")
} else {
    $app = @("main:app", "--app-dir", "src")
}

# psycopg async needs the selector loop on Windows.
uv run uvicorn @app --host 0.0.0.0 --port $Port `
    --loop asyncio:SelectorEventLoop `
    --ssl-keyfile $key --ssl-certfile $cert
