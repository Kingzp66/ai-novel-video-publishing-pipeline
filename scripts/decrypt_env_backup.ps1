param(
    [string]$EncryptedPath = "encrypted-backups/env.backup.enc.json",
    [string]$PassphrasePath = "encrypted-backups/env.backup.passphrase.txt",
    [string]$OutputPath = ".env.restored"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $EncryptedPath)) {
    throw "Encrypted backup not found: $EncryptedPath"
}
if (-not (Test-Path -LiteralPath $PassphrasePath)) {
    throw "Passphrase file not found: $PassphrasePath"
}

$backup = Get-Content -LiteralPath $EncryptedPath -Raw | ConvertFrom-Json
$passphrase = (Get-Content -LiteralPath $PassphrasePath -Raw).Trim()

$salt = [Convert]::FromBase64String($backup.salt_b64)
$iv = [Convert]::FromBase64String($backup.iv_b64)
$ciphertext = [Convert]::FromBase64String($backup.ciphertext_b64)
$iterations = [int]$backup.iterations

$derive = [System.Security.Cryptography.Rfc2898DeriveBytes]::new(
    $passphrase,
    $salt,
    $iterations,
    [System.Security.Cryptography.HashAlgorithmName]::SHA256
)
$key = $derive.GetBytes(32)

$aes = [System.Security.Cryptography.Aes]::Create()
$aes.Mode = [System.Security.Cryptography.CipherMode]::CBC
$aes.Padding = [System.Security.Cryptography.PaddingMode]::PKCS7
$aes.KeySize = 256
$aes.Key = $key
$aes.IV = $iv

$decryptor = $aes.CreateDecryptor()
$plaintextBytes = $decryptor.TransformFinalBlock($ciphertext, 0, $ciphertext.Length)
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText((Join-Path (Get-Location) $OutputPath), [System.Text.Encoding]::UTF8.GetString($plaintextBytes), $utf8NoBom)
Write-Host "Decrypted backup to $OutputPath"
