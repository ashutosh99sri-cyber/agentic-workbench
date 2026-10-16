import unittest

from app import discounted_total


class DiscountTests(unittest.TestCase):
    def test_percentage_discount(self) -> None:
        self.assertEqual(discounted_total(1000, 10), 900)

    def test_boundary_values(self) -> None:
        self.assertEqual(discounted_total(1000, 0), 1000)
        self.assertEqual(discounted_total(1000, 100), 0)
        with self.assertRaises(ValueError):
            discounted_total(-1, 10)


if __name__ == "__main__":
    unittest.main()
