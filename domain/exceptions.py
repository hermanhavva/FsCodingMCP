class DomainException(Exception): 
    pass

class SandboxViolationError(DomainException): 
    pass

class InvalidExtensionError(DomainException): 
    pass