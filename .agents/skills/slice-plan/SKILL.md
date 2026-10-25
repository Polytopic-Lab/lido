---
name: slice-plan
description: Produce the implementation plan for one Lido slice, written to doc/slices/<id>-<slug>.md. Use when asked to plan a slice, or when the user names a slice ID from doc/plan.md and wants a plan rather than code. Step 1 of the two-step slice loop in doc/development.md; slice-implement is step 2.
---

Read `doc/prompts/slice-plan.md` and follow it.

The slice ID is the argument. Take it from the user's message — e.g. "plan
slice 2.2" means `<slice-id>` = `2.2`. If the message does not name one,
ask for it before reading any other file.
