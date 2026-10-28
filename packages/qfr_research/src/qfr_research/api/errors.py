"""Safe HTTP error categories without backend paths, credentials or source text."""


class ResearchNotFound(ValueError):
    pass


class ResearchConflict(ValueError):
    pass


class ResearchUnavailable(RuntimeError):
    pass


class InvalidResearchRequest(ValueError):
    pass
