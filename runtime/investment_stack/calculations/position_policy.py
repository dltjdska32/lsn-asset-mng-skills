"""Shared v7 position policy. Thresholds request review, never an order."""
from decimal import Decimal

SINGLE_REVIEW = Decimal('.25')
SINGLE_HIGH_REVIEW = Decimal('.30')
TOP_TWO_REVIEW = Decimal('.50')
TINY_POSITION = Decimal('.01')
CASH_FLOOR = Decimal('.10')
GUIDANCE = '참고 범위: 핵심 고확신 15~30%, 보조 성장 8~15%, 고위험·테마 2~8%. 고정 목표비중이 아니며 30% 초과도 자동매도하지 않습니다.'
POLICY_B_GUIDANCE = 'D12 B: 검증된 적정가의 80%·75%·70%에서 분할 검토, 투자현금 하한 10%. 증액 금액은 검증된 승인 위험예산과 가용현금으로 제한하며 집중도는 v7 정책에 따라 검토합니다. 정책은 거래 승인이 아닙니다.'

def concentration(weight):
    if weight is None:
        return 'UNKNOWN'
    return 'HIGH' if weight > SINGLE_HIGH_REVIEW else 'REVIEW' if weight > SINGLE_REVIEW else 'WITHIN_REVIEW_THRESHOLDS'
