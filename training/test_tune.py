import copy
import unittest

from training.tune import select_candidate, validate_negative_record


class NegativeValidationTests(unittest.TestCase):
    def setUp(self):
        self.catalog={"source":{"split":"train","group":"training-group","image_sha256":"sha",
                                "width":2048,"height":2048,"boxes":[[.75,.75,1.,1.]]}}
        self.item={"source_id":"source","group":"training-group","source_sha256":"sha",
                   "review":"accepted_no_visible_cattle","x":0,"y":0,"size":1024}

    def test_training_background_is_accepted(self):
        self.assertEqual(validate_negative_record(self.item,self.catalog),self.catalog["source"])

    def test_validation_and_test_are_rejected_even_if_reviewed(self):
        for split in ("val","test","excluded"):
            with self.subTest(split=split):
                catalog=copy.deepcopy(self.catalog);catalog["source"]["split"]=split
                with self.assertRaisesRegex(ValueError,"training split"):
                    validate_negative_record(self.item,catalog)

    def test_even_a_cow_fragment_is_rejected(self):
        item={**self.item,"x":513,"y":513}
        with self.assertRaisesRegex(ValueError,"annotated cow"):
            validate_negative_record(item,self.catalog)

    def test_boundary_touch_without_overlap_is_allowed(self):
        validate_negative_record({**self.item,"x":512,"y":512},self.catalog)

    def test_review_and_identity_are_required(self):
        for key,value in (("review","pending"),("source_sha256","changed"),("group","held-out-group")):
            with self.subTest(key=key),self.assertRaises(ValueError):
                validate_negative_record({**self.item,key:value},self.catalog)

    def test_invalid_coordinates_are_rejected(self):
        for change in ({"x":-1},{"y":1025},{"size":512},{"x":.5}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                validate_negative_record({**self.item,**change},self.catalog)


class RecallSelectionTests(unittest.TestCase):
    def candidate(self, name="safe", *, overall=.86, dense=.86, group=.82, disagreements=200):
        return {"variant":name,"confidence":.3,"nms_iou":.5,
                "metrics":{"annotation_recall":overall,"annotation_disagreements":disagreements,"count_mae_vs_annotations":3.},
                "dense_images":{"annotation_recall":dense},
                "by_group":{"one":{"annotation_recall":group},"two":{"annotation_recall":.93}}}

    def test_dense_herd_recall_cannot_hide_behind_average(self):
        bad=self.candidate("bad",overall=.93,dense=.70,disagreements=100)
        good=self.candidate()
        self.assertEqual(select_candidate([bad,good]),good)

    def test_capture_group_recall_cannot_hide_behind_average(self):
        bad=self.candidate("bad",overall=.93,group=.70,disagreements=100)
        good=self.candidate()
        self.assertEqual(select_candidate([bad,good]),good)

    def test_unmet_target_is_reported_without_lowering_floor(self):
        self.assertIsNone(select_candidate([self.candidate(overall=.84)]))

    def test_exact_floor_and_policy_override(self):
        candidate=self.candidate(overall=.90,dense=.90,group=.85)
        self.assertEqual(select_candidate([candidate],recall_floor=.9,dense_recall_floor=.9,group_recall_floor=.85),candidate)

    def test_disagreements_select_only_among_eligible_candidates(self):
        safe=self.candidate("safe",disagreements=200)
        better=self.candidate("better",disagreements=150)
        self.assertEqual(select_candidate([safe,better]),better)


if __name__=="__main__":
    unittest.main()
