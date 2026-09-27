"""The code that runs inside the sandbox container.

Kept out of `app/` deliberately: nothing in this package may be imported by the
host process. The host has no pandas and should not acquire one - the only
thing it does with a frame is describe it in aggregate.
"""
