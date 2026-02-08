from passlib.context import CryptContext

# Password Hashing Context
# Using bcrypt as the scheme
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifies a plain password against a stored hash.
    Args:
        plain_password: The password attempt.
        hashed_password: The stored hash to compare against.
    Returns:
        True if the password matches the hash, False otherwise.
    """
    return pwd_context.verify(plain_password.strip(), hashed_password)


def get_password_hash(password: str) -> str:
    """
    Generates a hash for a given password.
    Args:
        password: The plain text password to hash.
    Returns:
        The generated password hash.
    """
    return pwd_context.hash(password.strip())
