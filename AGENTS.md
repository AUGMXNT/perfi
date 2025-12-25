Please refer to `docs/README.md`, `docs/PLAN.md` and `docs/IMPLEMENTATION.md` all project-specific details. 
This `AGENTS.md`/`CLAUDE.md` is specifically for ground rules, process and behavior notes.

## General
- Treat our docs/ as the source of truth and always prioritize keeping them up to date.
- All work should be logged into the `docs/IMPLEMENTATION.md`. Multiple Agents will be coordinating, so please be careful and sensitive to others' work. Prefer to append/patch the shared docs to not step over others. Each agent will usually be responsible for working on specific tasks/features, coordinated by the user/operator that we will refer to in this doc as the LEAD.
- When assigned a task, work independently on that task until fully complete. When appropriate it's best to test before writing code to ensure everything is working as expected, and then to document the progress when complete. Any outstanding issues (implementation details, ambiguities, etc) can be addressed with the LEAD once the basic task is complete.
- If you run into permissions issues or other blockers, stop immediately and request the LEAD to resolve or give further direction.
- We use conda/mamba environments and it's important to use `mamba run` in the proper environment. Be sure to run scripts/tests in the appropriate environment.

## Shared Workflow Expectations
- **Before picking up work:** skim the latest updates (git log/status/diff can help for tracking updates); confirm open checkboxes in our IMPLEMENTATION.md aligns with your plan.
- **During execution:** leave concise breadcrumbs (commands run, datasets touched, intermediate outputs) in the IMPLEMENTATION. Our goal is to be able to refer to our docs and be able to pick back up easily.
- **After changes:** reflect status in IMPLEMENTATION.md (check/annotate items), note deliverables or blockers here under a dated section.
- Sometimes the LEAD will request a feature-specific PLAN/IMPLEMENTATION - in that case, create detailed updates in the task-specific docs, but leave a pointer in the global docs as well.

## Coordination and Committing
- Keep filenames ASCII and avoid destructive git actions, be *very* specific when making edits or commits to avoid trampling on others' work.
- We often have nested or multiple repos (not a mono-repo) so always be aware of what path you are in and what repo you're working in. When in doubt, double-check.
- You will only commit updates after review with the LEAD (or if the LEAD has pre-approved).
- Whenever checking in code it's VERY IMPORTANT to only add individual files to our commits so we don't accidentally add temporary or other agent's work, just our own.
- Commit messages should be concise - a one line summary, with bullet points for major features/changes. No authorship, footers, or additional boiler plate clogging up our commit logs.
- When committing, we should commit files grouped by task (eg, separate commits for each task).
- If there is any confusion, flag the LEAD for further instruction.
