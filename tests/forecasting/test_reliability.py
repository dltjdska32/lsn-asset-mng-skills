from investment_stack.forecasting.backtest import reliability_from_walkforward_results

def test_relative_reliability_rewards_lower_error_and_direction():
    r=reliability_from_walkforward_results({
      'a':{'mae':0.05,'directional_accuracy':0.7},
      'b':{'mae':0.10,'directional_accuracy':0.6},
    }, experimental_compat=True)
    assert r['a'] > r['b']
    assert abs(sum(r.values())/len(r)-1.0) < 1e-12
