class RateLimitException(Exception):
    def __init__(
        self,
        message,
        requests_limit=None,
        requests_period=None,
        last_period_start_time=None,
    ):
        self.message = message
        self.requests_limit = requests_limit
        self.requests_period = requests_period
        self.last_period_start_time = last_period_start_time
        super().__init__(message)
