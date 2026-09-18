class TransactionServiceError(Exception):
    """Base exception for transaction-service errors."""


class UserNotFoundError(TransactionServiceError):
    pass


class MerchantNotFoundError(TransactionServiceError):
    pass


class AccountNotFoundError(TransactionServiceError):
    pass


class InsufficientFundsError(TransactionServiceError):
    pass


class IdempotencyConflictError(TransactionServiceError):
    pass
