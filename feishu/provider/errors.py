class ProgramError(Exception):
    """A protocol-v1 connector error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
