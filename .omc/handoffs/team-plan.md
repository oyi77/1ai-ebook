## Handoff: team-plan → team-exec

- **Decided**: 5-workstream execution: Phase 1 first (serial prerequisite), then Phases 2+3/4/5 in parallel, then Phase 6. Plan at .omc/plans/ebook-improvements.md (Rev 3, consensus-approved).
- **Rejected**: Full async DAG orchestrator (orchestrator source exists but scope too large); external services (DeepL, Midjourney) out of OmniRoute ecosystem.
- **Risks**: ManuscriptEngine becomes complex — extract _build_system_prompt(); probe_image_support uses lazy detection on first generate_image() call; get_edition_dir() takes primary_lang param (not hardcoded "en").
- **Files**: .omc/plans/ebook-improvements.md (approved plan)
- **Remaining**: Phase 1 must complete before Phases 2–5 can start. Phase 6 waits for 2–5. Orchestrator source confirmed at src/pipeline/orchestrator.py (223 lines, readable).
