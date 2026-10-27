# ADB Flow Studio — Desktop MVP

ADB Flow Studio is the first Windows desktop interface for the existing ADB-only gesture recorder and replayer. This branch adds the desktop shell and connects it to the scripts in tools/adb_gesture_recorder.py and tools/adb_gesture_replayer.py.

## Current MVP features

- Dashboard with ADB/device status and saved workflow list.
- ADB executable auto-detection and a manual path setting.
- Capture page with output JSON selection, Stop and Save, optional foreground/window snapshots, and optional UI-text snapshots.
- Replay page with workflow selection, repeat count, delay between runs, progress, Stop, and per-run logs.
- Dry Run is enabled by default. Real replay requires a confirmation prompt.
- Screen-state verification is disabled by default to match the current ADB-only workflow. It can be enabled explicitly for a replay.
- Logs and workflow JSON files are stored in the user's Documents folder.

## Important status

**This MVP is not ready for commercial sale yet.** The offline Ed25519 license validation and activation UI are implemented, but the seller must generate and embed their own public signing key before building a license-enforced release. The Windows installer still needs clean-machine testing and a real-device end-to-end test.

The desktop GUI does not remove the underlying ADB limitations: capture is single-finger; some Android/OEM builds block getevent; and ADB shell input approximates recorded curved swipes as straight swipes.

## Run from source on Windows

1. Install Python 3.11 or newer.
2. Install Android Platform Tools and make sure the phone is authorized for USB debugging.
3. From the repository root, run these commands:

    python -m pip install -r requirements-desktop.txt
    python desktop\main.py

4. If ADB is not detected, open Settings in the app and browse to adb.exe.
5. Capture workflows are saved by default under %USERPROFILE%\Documents\ADB Flow Studio\workflows.
6. Replay logs are saved under %USERPROFILE%\Documents\ADB Flow Studio\logs.

## Run tests

    python -m unittest discover -s desktop\tests -v
    python -m compileall -q desktop tools

## Build the Windows installer

1. Install Python 3.11 or newer and Android Platform Tools.
2. Run desktop\build_windows.bat from a Windows checkout. This builds the GUI, recorder helper, and replayer helper into dist\.
3. Install Inno Setup 6 on the build PC.
4. Run desktop\build_installer.bat. The installer is created at dist\ADBFlowStudioSetup.exe.
5. The Windows Desktop Build workflow also builds the installer, tests both helper executables, silently installs and uninstalls the setup package, and uploads an installer artifact for 14 days. See the GitHub Actions page: https://github.com/mahirlabib478-del/automation-ui/actions.

The recommended customer package is ADBFlowStudioSetup.exe. The three standalone executables must stay together if you distribute them without the installer.

**Commercial release warning:** the default CI build is a developer build unless desktop\licensing\license_public_key.py exists. Generate your own signing keypair and embed the public key before selling. The application is not code-signed, and a real Android-device test is still required before release.

## Offline licensing setup for the seller

The signed-license system uses Ed25519 and validates licenses locally. The first source build runs in development mode until you embed your own public signing key.

1. Generate a keypair on a trusted PC:

    python tools\license_admin.py generate-keys

2. Enter a strong passphrase when prompted. The encrypted private key is written by default to Documents\ADB Flow Studio Admin\license_private_key.pem, outside the repository. The public module is created at desktop\licensing\license_public_key.py. The public module is safe to commit; the private key and passphrase must never be committed or sent to customers.
3. Build a license-enforced release from a checkout that contains your public module:

    set REQUIRE_LICENSE=1 && desktop\build_windows.bat && desktop\build_installer.bat

4. On a customer's PC, open the License page and copy the displayed Machine ID. Issue a license on the trusted seller PC:

    python tools\license_admin.py issue --private-key "C:\secure\license_private_key.pem" --machine-id "PASTE-MACHINE-ID" --customer "Customer Name" --output customer-license.txt

   Omit the --expires argument for a perpetual license. To issue an expiring license, add --expires YYYY-MM-DD.
5. Send only the license key from customer-license.txt to the customer. They paste it into the License page and select Activate License.

Offline licenses cannot be remotely revoked without a future online check. A Windows reinstall or machine identity change can require a replacement license. The seller should keep a secure backup of the encrypted private key and passphrase.
