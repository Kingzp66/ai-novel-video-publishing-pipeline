# Encrypted Environment Backup

This folder stores encrypted backups of local secret files.

`env.backup.enc.json` is an AES-256 encrypted backup of the local `.env` file.
The passphrase is intentionally not committed. On this machine it is stored at:

```text
encrypted-backups/env.backup.passphrase.txt
```

Restore locally with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\decrypt_env_backup.ps1
```

By default, the script writes the decrypted file to `.env.restored`.
