import unittest
from unittest.mock import patch
from motor.harness.forecast_bench import aggregate, evaluate_case, summarize

class ForecastBenchTests(unittest.TestCase):
    def test_denominators_and_empty(self):
        rows=[{'predicted':4,'crossings':8,'hits':2,'leads':[3,7],'censored':1}]
        self.assertEqual(aggregate(rows),{'precision':.5,'recall':.25,'median_lead_min':5})
        self.assertIsNone(aggregate([])['precision'])
        a=summarize(rows,bootstrap=20)
        self.assertEqual(a['n'],1)
        self.assertEqual(a['metrics']['precision']['ci95'],[.5,.5])

    def test_future_shock_counts_as_miss_without_prediction(self):
        case={'id':'unseen','seed':42,'duration_min':18,'initial':{'spontaneous':False},
              'events':[{'t':2,'kind':'zone_flag','zone':'water_n','flag':'water_l','value':0}]}
        with patch('motor.harness.forecast_bench.forecast',return_value=[]):
            r=evaluate_case(case)
        self.assertGreaterEqual(r['crossings'],1)
        self.assertEqual(r['hits'],0)
        self.assertEqual(r['predicted'],0)

if __name__=='__main__':
    unittest.main()
