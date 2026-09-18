import os
import pytest

# Inject test environment to bypass production secrets validation without
# triggering the 'development' mode which bypasses authentication.
os.environ["ENV"] = "test"

# Also set strong secrets just in case any test expects them
os.environ["SECRET_KEY"] = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
os.environ["ADMIN_PASSWORD"] = "StrongAdminTest123!"
os.environ["INITIAL_OPERATOR_PASSWORD"] = "StrongOperatorTest123!"
os.environ["INITIAL_AUDITOR_PASSWORD"] = "StrongAuditorTest123!"

