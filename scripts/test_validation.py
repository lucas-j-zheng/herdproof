import unittest
from aerial_metrics import match_boxes, evaluate, aggregate
from reconcile_inventory import read_records, reconcile
from serve_validation import point_accuracy

CSV = "document_id,date,event,pen,quantity\nI1,2026-09-01,inventory,A,20\nI2,2026-09-01,inventory,B,10\nS1,2026-09-03,sale,A,4\nP1,2026-09-08,purchase,A,7\n"


class ValidationTests(unittest.TestCase):
    def test_equal_counts_can_hide_two_errors(self):
        r = {"id":"x", "flight":"f", "split":"evaluation", "boxes":[[0,0,.1,.1]]}
        score = evaluate(r, [[.8,.8,.9,.9,.8]], .5)
        self.assertEqual((score["error"], score["fp"], score["fn"]), (0,1,1))

    def test_duplicate_prediction_only_matches_once(self):
        b = [0,0,1,1]
        result = match_boxes([b,b], [b])
        self.assertEqual(len(result["matches"]), 1)
        self.assertEqual(len(result["fp_indices"]), 1)

    def test_augmenting_match_avoids_greedy_undercount(self):
        predictions = [[0,0,.75,1], [0,0,.5,1]]
        truth = [[0,0,.5,1], [.25,0,.75,1]]
        self.assertEqual(len(match_boxes(predictions, truth)["matches"]), 2)

    def test_empty_truth_precision_is_not_invented(self):
        r = {"id":"x", "flight":"f", "split":"evaluation", "boxes":[]}
        self.assertIsNone(aggregate([evaluate(r, [], .5)])["recall"])

    def test_missing_pen_not_a_shortage(self):
        result = reconcile(read_records(CSV), {"A": {"count":16,"reviewed":True,"coverage":"complete","as_of":"2026-09-05"}}, "2026-09-05")
        self.assertEqual(result["expected_total"], 26)
        self.assertIsNone(result["observed_total"])
        self.assertIsNone(result["pens"][1]["difference"])
        self.assertEqual(result["pens"][0]["ignored_future_documents"], ["P1"])

    def test_zero_is_valid_observation_not_missing(self):
        result = reconcile(read_records(CSV), {"A": {"count":0,"reviewed":True,"coverage":"complete","as_of":"2026-09-05"}}, "2026-09-05")
        self.assertEqual(result["pens"][0]["difference"], -16)

    def test_stale_and_unreviewed_counts_stay_incomplete(self):
        for reviewed, captured in ((False,"2026-09-05"),(True,"2026-09-04")):
            result = reconcile(read_records(CSV), {"A":{"count":16,"reviewed":reviewed,"coverage":"complete","as_of":captured}}, "2026-09-05")
            self.assertEqual(result["pens"][0]["status"], "incomplete")

    def test_duplicate_document_rejected(self):
        with self.assertRaises(ValueError): read_records(CSV + "S1,2026-09-04,sale,A,4\n")

    def test_negative_inventory_rejected(self):
        with self.assertRaises(ValueError): reconcile(read_records(CSV.replace(",sale,A,4",",sale,A,40")), {}, "2026-09-05")

    def test_same_day_transaction_needs_ordering(self):
        with self.assertRaises(ValueError): reconcile(read_records(CSV.replace("2026-09-03", "2026-09-01")), {}, "2026-09-05")

    def test_review_duplicate_points_are_false_marks(self):
        score = point_accuracy([[.5,.5],[.5,.5]], [[0,0,1,1]])
        self.assertEqual((score["matched"],score["false_marks"],score["missed"]),(1,1,0))

    def test_review_point_outside_cow_not_correct_even_when_count_matches(self):
        score = point_accuracy([[.9,.9]], [[0,0,.1,.1]])
        self.assertEqual((score["false_marks"],score["missed"]),(1,1))


if __name__ == "__main__": unittest.main()
