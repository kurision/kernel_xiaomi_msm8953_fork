#!/usr/bin/env bash
# Package the current Image.gz-dtb as a flashable AnyKernel3 zip.
set -euo pipefail

if [[ $# != 0 ]]; then
    echo "Usage: $0"
    echo "Overrides: OUT_DIR, ANYKERNEL_DIR"
    if [[ ${1:-} == --help ]]; then exit 0; fi
    exit 2
fi

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
for tool in python3; do
    command -v "$tool" >/dev/null || { echo "Missing tool: $tool" >&2; exit 1; }
done

python3 - "${OUT_DIR:-$repo_dir/out}" "${ANYKERNEL_DIR:-$repo_dir/../AnyKernel3}" <<'PY'
from pathlib import Path
import hashlib
import re
import sys
import tempfile
import zipfile

out, template = [Path(arg).resolve() for arg in sys.argv[1:]]
kernel = out / 'arch/arm64/boot/Image.gz-dtb'
release = (out / 'include/config/kernel.release').read_text().strip()
if not re.fullmatch(r'[A-Za-z0-9._+-]+', release):
    sys.exit('Invalid kernel release in build output')
for path in (kernel, template / 'anykernel.sh',
             template / 'META-INF/com/google/android/update-binary',
             template / 'tools/ak3-core.sh', template / 'tools/magiskboot'):
    if not path.is_file():
        sys.exit(f'Missing input: {path}')

zip_output = out / f'tissot-{release}.zip'
with tempfile.TemporaryDirectory(prefix='package-tissot-', dir=out) as directory:
    work = Path(directory)
    archive = work / 'kernel.zip'
    installer = (template / 'anykernel.sh').read_text()
    installer, replacements = re.subn(
        r'^kernel.string=.*$', f'kernel.string=tissot {release}',
        installer, flags=re.MULTILINE)
    if replacements != 1:
        sys.exit('Expected one kernel.string in AnyKernel3 installer')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zipped:
        for path in sorted(template.rglob('*')):
            relative = path.relative_to(template)
            if (not path.is_file() or
                    any(part.startswith('.') for part in relative.parts) or
                    'placeholder' in path.name or
                    relative.parts[0] not in
                    ('META-INF', 'tools', 'modules', 'patch', 'ramdisk', 'LICENSE')):
                continue
            zipped.write(path, str(relative))
        info = zipfile.ZipInfo.from_file(template / 'anykernel.sh', 'anykernel.sh')
        info.compress_type = zipfile.ZIP_DEFLATED
        zipped.writestr(info, installer)
        zipped.write(kernel, 'Image.gz-dtb')
    with zipfile.ZipFile(archive) as zipped:
        if zipped.testzip() or zipped.read('Image.gz-dtb') != kernel.read_bytes():
            sys.exit('Kernel zip verification failed')
    archive.replace(zip_output)

print('Verified flashable kernel zip.')
print(f'{zip_output}\n  SHA256: {hashlib.sha256(zip_output.read_bytes()).hexdigest()}')
PY
