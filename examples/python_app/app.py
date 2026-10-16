"""Deliberate regression fixture: discounts should apply to the amount."""


def discounted_total(amount_cents: int, discount_percent: int) -> int:
    if type(amount_cents) is not int or amount_cents < 0:
        raise ValueError("Amount must be nonnegative integer cents")
    if type(discount_percent) is not int or not 0 <= discount_percent <= 100:
        raise ValueError("Discount must be an integer percentage from 0 to 100")
    return amount_cents - discount_percent
