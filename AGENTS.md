# FACO private-development operating instructions

Scope: user-owned FACO applications and their privately tested development branches. This file is guidance for code changes, not an application feature, release, or replacement safety module.

- Implement exactly the functionality requested. Prefer working features over scaffolding, decorative UI, placeholder controls, mock success, or legalistic declarations.
- Keep GUI interfaces streamlined and discoverable. Include a relevant functional Options tab/panel, without redundant menus or unnecessary settings.
- Treat an explicit request to build/debug/test as authorization for ordinary in-scope reversible development; avoid repeating approval prompts, forced sign-offs, and unnecessary review forms.
- For private development, do not require release packaging, public distribution, or production enrollment before local tests can run.
- Preserve real account/network authentication, required platform permissions, confidential credentials, data integrity, recoverable user data and functioning regression tests. Do not invent extra application-level restrictions beyond what the implementation actually needs.
- No standalone Safety Rules module, new security-dashboard placeholder, default-deny UX screen, or speculative guardrail scaffolding.
- Use the existing FACO source, resources, and project structure. Do not copy/rebuild working infrastructure or swap source roots without evidence.
- Use Google Drive for cloud artifacts and project continuity instead of Dropbox unless the user specifically asks otherwise; keep canonical spelling FACO and Blackbird.
- Source changes, tests, commits, installed builds, and real user acceptance are different states. Never report unrun tests or uninstalled changes as done.
- Do not merge or install these development-branch changes on the live workstation or publish applications merely because an instruction file exists.
