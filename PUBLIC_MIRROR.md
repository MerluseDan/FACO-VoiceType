# Temporary public mirror of FACO Resource Watch

This branch is a temporary, full-source public mirror because the connected GitHub integration can publish files and create branches, but cannot create a new repository. The default branch of `MerluseDan/FACO-VoiceType` is unchanged. The project will be moved to `MerluseDan/FACO-Resource-Watch` once that standalone repository exists.

## Install

Download the ZIP of **this branch**, extract it, then run `./install.sh` from the extracted folder. Defaults use standard Linux XDG directories, never private workstation drives. The background collector is a user-level systemd service.

## Status

Automated tests passed on Linux in the build environment. The actual GNOME panel and NVIDIA sensor integration must still be confirmed on end-user hardware.

This is not a new VoiceType release. Do not merge the Resource Watch mirror branch into VoiceType's `main` branch.
