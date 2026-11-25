# Extension contract (ARCH-13)

The extension is not in this repository (decision O-1). This file states what it may do with the installer; `installer/update.py` holds the host check (`extension_may_drive`, `update_available`). INST-REQ-011, 037, 081, 082.

## The extension may

- Tell the user that a newer version exists (`update_available`: newer, same major version) and open the build screen (037).
- Offer one command that builds the installer from source and start it only after the confirmation screen (011).
- Run a command only after the user confirmed it on that screen.
- Read the state file `installer-state.json` (schema: `state.schema.json`) to learn the installed version.

## The extension may never

- Fetch installer code or run installer code it did not build from source (081).
- Drive an installer whose major version differs from its own (082): `extension_may_drive` refuses with `major-version-mismatch`.
- Update, repair or uninstall by itself: it only opens the installer, which does the work.
- Read, show or pass on a secret.
