import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import pandas as pd
import unittest
from evidence import calculate_evidence, amount_score, date_score
from matching import match_settlement
from services.date_reasoning import business_day_difference
from source_classification import classify_bank_transaction

class TestReconciliation(unittest.TestCase):

    def setUp(self):
        self.settlement_1 = pd.Series({
            "settlement_id": "setl_test_1",
            "settlement_date": pd.Timestamp("2026-06-18"),
            "net_amount": 100000.00,
            "settlement_cycle": "standard_t+2",
            "settlement_utr": "RZP123"
        })
        
    def test_amount_evidence(self):
        # Exact match 100 -> 100 (which is 75 in our weights)
        self.assertEqual(amount_score(100000.0, 100000.0), 75.0)
        
        # Small amount difference (<=1.00 tolerance) -> 90% of max = 67.5
        self.assertEqual(amount_score(100000.0, 99999.50), 67.5)
        
        # Larger difference (percentage diff < 1.0) -> 80% of max = 60.0
        self.assertEqual(amount_score(100000.0, 99500.00), 60.0)

    def test_date_evidence(self):
        # same business day
        self.assertEqual(business_day_difference("2026-06-18", "2026-06-18"), 0)
        
        # Weekend Friday -> Monday (June 19 2026 is Friday, June 22 is Monday)
        self.assertEqual(business_day_difference("2026-06-19", "2026-06-22"), 1)
        
        # Weekend Friday -> Tuesday
        self.assertEqual(business_day_difference("2026-06-19", "2026-06-23"), 2)

    def test_wrong_transaction_type(self):
        # Debit transaction should not match
        bank_rows = pd.DataFrame([{
            "bank_date": pd.Timestamp("2026-06-18"),
            "bank_amount": 100000.00,
            "is_credit": False,
            "transaction_type": "UNKNOWN",
            "narration": "DEBIT FOR SOMETHING"
        }])
        evidence = calculate_evidence(self.settlement_1, bank_rows)
        self.assertEqual(evidence["transaction_type_score"], 0.0)

    def test_utr_match_narration(self):
        bank_rows = pd.DataFrame([{
            "bank_date": pd.Timestamp("2026-06-18"),
            "bank_amount": 100000.00,
            "is_credit": True,
            "transaction_type": "NEFT",
            "narration": "NEFT/RZP123/RAZORPAY"
        }])
        evidence = calculate_evidence(self.settlement_1, bank_rows)
        self.assertEqual(evidence["narration_score"], 3.0)

    def test_competition_resolutions(self):
        # 100 vs 70 -> MATCHED
        bank = pd.DataFrame([
            {
                "bank_reference": "REF1",
                "bank_date": pd.Timestamp("2026-06-18"),
                "bank_amount": 100000.00,
                "is_credit": True,
                "transaction_type": "NEFT",
                "narration": "RAZORPAY"
            },
            {
                "bank_reference": "REF2",
                "bank_date": pd.Timestamp("2026-06-22"),  # later date
                "bank_amount": 100000.00,
                "is_credit": True,
                "transaction_type": "TRANSFER",
                "narration": "UNKNOWN"
            }
        ])
        
        claimed = set()
        result = match_settlement(self.settlement_1, bank, claimed)
        self.assertEqual(result["status"], "MATCHED")
        self.assertEqual(result["bank_index"], 0)
        
        # Equal competition 100 vs 100 -> REVIEW
        bank_equal = pd.DataFrame([
            {
                "bank_reference": "REF1",
                "bank_date": pd.Timestamp("2026-06-18"),
                "bank_amount": 100000.00,
                "is_credit": True,
                "transaction_type": "NEFT",
                "narration": "RAZORPAY"
            },
            {
                "bank_reference": "REF2",
                "bank_date": pd.Timestamp("2026-06-18"),
                "bank_amount": 100000.00,
                "is_credit": True,
                "transaction_type": "NEFT",
                "narration": "RAZORPAY"
            }
        ])
        result_equal = match_settlement(self.settlement_1, bank_equal, set())
        self.assertEqual(result_equal["status"], "REVIEW")
        self.assertIsNone(result_equal["bank_index"])
        
    def test_weak_competition(self):
        # Weak competition 94 vs 60 -> REVIEW because top is below 95
        bank = pd.DataFrame([
            {
                "bank_reference": "REF1",
                "bank_date": pd.Timestamp("2026-06-18"),
                "bank_amount": 100000.00,
                "is_credit": True,
                "transaction_type": "UNKNOWN", # will lose some points -> < 95
                "narration": "UNKNOWN" # will lose some points -> < 95
            },
            {
                "bank_reference": "REF2",
                "bank_date": pd.Timestamp("2026-06-25"),
                "bank_amount": 100000.00,
                "is_credit": True,
                "transaction_type": "UNKNOWN",
                "narration": "UNKNOWN"
            }
        ])
        result = match_settlement(self.settlement_1, bank, set())
        self.assertEqual(result["status"], "REVIEW")
        
    def test_bank_row_reuse(self):
        bank = pd.DataFrame([
            {
                "bank_reference": "REF1",
                "bank_date": pd.Timestamp("2026-06-18"),
                "bank_amount": 100000.00,
                "is_credit": True,
                "transaction_type": "NEFT",
                "narration": "RAZORPAY"
            }
        ])
        # If it's already in claimed_bank_indices, it should return UNMATCHED
        claimed = {0}
        result = match_settlement(self.settlement_1, bank, claimed)
        self.assertEqual(result["status"], "UNMATCHED")
        
    def test_grouped_candidate(self):
        # 40k + 60k = 100k
        bank_rows = pd.DataFrame([
            {
                "bank_date": pd.Timestamp("2026-06-18"),
                "bank_amount": 40000.00,
                "is_credit": True,
                "transaction_type": "NEFT",
                "narration": "RAZORPAY PART 1"
            },
            {
                "bank_date": pd.Timestamp("2026-06-18"),
                "bank_amount": 60000.00,
                "is_credit": True,
                "transaction_type": "NEFT",
                "narration": "RAZORPAY PART 2"
            }
        ])
        
        evidence = calculate_evidence(self.settlement_1, bank_rows)
        # 40k + 60k = 100k which is exact match
        self.assertEqual(evidence["amount_score"], 75.0)

    def test_source_classification(self):
        known_customers = {"ABC TRADERS"}
        known_invoices = {"1023"}

        # CASE 1: Bank row contains RZP
        row1 = {"bank_reference": "RZP2026", "is_credit": True}
        res1 = classify_bank_transaction(row1, known_customers, known_invoices)
        self.assertEqual(res1["source"], "RAZORPAY")
        
        # CASE 2: NEFT but no Razorpay
        row2 = {"narration": "NEFT TRANSFER", "is_credit": True}
        res2 = classify_bank_transaction(row2, known_customers, known_invoices)
        self.assertNotEqual(res2["source"], "RAZORPAY")
        
        # CASE 3: Customer name + invoice
        row3 = {"narration": "NEFT ABC TRADERS INV1023", "is_credit": True}
        res3 = classify_bank_transaction(row3, known_customers, known_invoices)
        self.assertEqual(res3["source"], "DIRECT_LEDGER")
        
        # CASE 4: Generic narration only
        row4 = {"narration": "CREDIT", "is_credit": True}
        res4 = classify_bank_transaction(row4, known_customers, known_invoices)
        self.assertEqual(res4["source"], "UNKNOWN")

if __name__ == '__main__':
    unittest.main()
