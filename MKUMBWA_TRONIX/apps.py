from django.apps import AppConfig


class MkumbwaTronixConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'MKUMBWA_TRONIX'

    def ready(self):
        import MKUMBWA_TRONIX.signals