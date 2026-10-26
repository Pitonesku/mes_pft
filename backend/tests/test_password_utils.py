import unittest

from app.password_utils import hash_password, verify_password, is_bcrypt_hash


class PasswordUtilsTest(unittest.TestCase):
    def test_hash_and_verify_roundtrip(self):
        h = hash_password("correct horse")
        self.assertTrue(h.startswith("$2"))
        self.assertTrue(verify_password("correct horse", h))
        self.assertFalse(verify_password("wrong", h))

    def test_empty_plaintext_rejected(self):
        h = hash_password("secret")
        self.assertFalse(verify_password("", h))

    def test_plaintext_stored_hash_rejected(self):
        # The old plain-text comparison fallback is gone.
        self.assertFalse(verify_password("123", "123"))

    def test_empty_stored_hash_rejected(self):
        self.assertFalse(verify_password("", ""))
        self.assertFalse(verify_password("anything", ""))

    def test_is_bcrypt_hash(self):
        self.assertTrue(is_bcrypt_hash(hash_password("x")))
        self.assertFalse(is_bcrypt_hash("plaintext"))
        self.assertFalse(is_bcrypt_hash(""))
        self.assertFalse(is_bcrypt_hash(None))


if __name__ == "__main__":
    unittest.main()
