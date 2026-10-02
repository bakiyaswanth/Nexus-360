"""Fail if anything that looks like a credential is committed. No third-party dependencies.

Usage: python scripts/check_no_secrets.py   (scans all git-tracked + untracked-not-ignored files)
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
PATTERNS = {
    "private key block": re.compile(r"-----BEGIN (?:RSA |EC |ENCRYPTED |OPENSSH )?PRIVATE KEY-----"),
    "password assignment": re.compile(r"""(?i)\b(password|passwd|pwd)\s*[:=]\s*["'][^"'\s]{6,}["']"""),
    "snowflake PAT / token": re.compile(r"""(?i)\b(token|pat|secret)\s*[:=]\s*["'][A-Za-z0-9_\-\.]{24,}["']"""),
    "inline RSA public key on user": re.compile(r"RSA_PUBLIC_KEY\s*=\s*'MII[A-Za-z0-9+/=]{100,}'"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
}
FORBIDDEN_FILES = re.compile(r"(\.p8|\.pem|\.key|secrets\.toml|connections\.toml|\.env)$", re.I)


def files():
    out = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, text=True)
    return [ROOT / f for f in out.splitlines() if f]


def main() -> int:
    findings = []
    for f in files():
        rel = f.relative_to(ROOT).as_posix()
        if FORBIDDEN_FILES.search(rel):
            findings.append(f"{rel}: credential file must not be committed")
            continue
        if f.suffix.lower() in {".wav", ".mp3", ".png", ".jpg", ".jpeg", ".pdf"} or not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for name, rx in PATTERNS.items():
            for m in rx.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                findings.append(f"{rel}:{line}: possible {name}")
    if findings:
        print("Secret scan FAILED:\n  " + "\n  ".join(findings))
        return 1
    print(f"Secret scan passed ({len(files())} files).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
