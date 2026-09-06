from __future__ import annotations

import unittest

from workflow_code_skeleton.app.services.task_lifecycle import TaskLifecycleMixin


class FrameworkToScriptProgressTests(unittest.TestCase):
    def test_stage11_coverage_counts_only_complete_reviewed_batches(self) -> None:
        complete_batch = {
            "batchStartEpisode": 1,
            "batchEndEpisode": 5,
            "batchPipelineStatus": "complete",
            "completedSubStages": [
                "causal_conflict_write",
                "causal_conflict_review",
                "causal_conflict_memory",
            ],
            "batchCausalConflictPlan": {"episodes": [{"episode": 1}]},
            "batchCausalConflictReview": {
                "reviewPassed": True,
                "rewriteRequired": False,
            },
            "conflictMemory": {"summary": "saved"},
        }
        incomplete_batch = {
            **complete_batch,
            "batchStartEpisode": 6,
            "batchEndEpisode": 10,
            "batchPipelineStatus": "running",
        }
        state = {
            "scriptStages": {
                "stage11": {"batches": {"1": complete_batch, "6": incomplete_batch}}
            }
        }

        covered, all_complete = TaskLifecycleMixin()._framework_to_script_stage11_coverage(
            state,
            10,
        )

        self.assertEqual(5, covered)
        self.assertFalse(all_complete)


if __name__ == "__main__":
    unittest.main()
