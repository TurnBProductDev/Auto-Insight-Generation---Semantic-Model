"""In-process services shared by the CLI, the config UI and the API.

Each module here is importable without side effects and without credentials.
They deliberately reuse the pipeline's own agents rather than re-implementing
them: a probe that predicts what a run will do must not be able to drift from
the run it predicts.
"""
