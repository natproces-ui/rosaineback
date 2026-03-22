# manager/__init__.py
from .gemini_client import model, model_json
from .logger import log_question, log_success, log_error, log_info

__all__ = ['model', 'model_json', 'log_question', 'log_success', 'log_error', 'log_info']