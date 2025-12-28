# manager/__init__.py
from .gemini_client import model
from .logger import log_question, log_success, log_error, log_info

__all__ = ['model', 'log_question', 'log_success', 'log_error', 'log_info']