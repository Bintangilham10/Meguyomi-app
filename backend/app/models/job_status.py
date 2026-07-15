from enum import StrEnum


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    READY_FOR_TRANSLATION = "READY_FOR_TRANSLATION"
    FAILED = "FAILED"
