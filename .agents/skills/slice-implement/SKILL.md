---
name: slice-implement
description: Implement one Lido slice from its approved plan in doc/slices/, then self-review and open the PR. Use when asked to implement or build a slice that already has an approved plan. Step 2 of the two-step slice loop in doc/development.md; slice-plan is step 1.
---

Read `doc/prompts/slice-implement.md` and follow it.

The slice ID is the argument. Take it from the user's message — e.g.
"implement slice 2.2" means `<slice-id>` = `2.2`. If the message does not
name one, ask for it before reading any other file.
