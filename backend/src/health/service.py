class HealthService:
    def status(self) -> str:
        return "OK"


def get_health_service() -> HealthService:
    return HealthService()
