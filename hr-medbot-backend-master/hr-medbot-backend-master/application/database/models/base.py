from sqlalchemy.orm import declarative_base


"""
Centralized Base context for all models.
"""

class _BaseSingleton:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = declarative_base()
        return cls._instance

Base = _BaseSingleton.get_instance()
