"""Safe, persistent creation diagnostics. Never retain exception text or proxy URLs."""
import subprocess

STEPS = ('checking_socks', 'checking_exit', 'reading_environment', 'preparing_storage',
         'saving_network', 'initializing_environment', 'creating_container',
         'starting_container', 'waiting_for_worker')
ERRORS = {
    'invalid_proxy_config', 'proxy_auth_method_rejected', 'proxy_auth_rejected',
    'proxy_connect_rejected', 'proxy_connection_failed', 'proxy_check_timeout',
    'network_guard_setup_failed', 'exit_tls_failed', 'exit_timezone_unavailable',
    'probe_runtime_failed', 'account_card_exists_no_reinitialize',
    'environment_inventory_failed', 'storage_prepare_failed', 'network_save_failed',
    'environment_initialize_failed', 'container_create_failed', 'container_start_failed',
    'container_readiness_failed', 'creation_interrupted', 'creation_failed',
}
DEFAULT_ERRORS = dict(zip(STEPS, (
    'proxy_connection_failed', 'exit_timezone_unavailable', 'environment_inventory_failed',
    'storage_prepare_failed', 'network_save_failed', 'environment_initialize_failed',
    'container_create_failed', 'container_start_failed', 'container_readiness_failed')))

class CreationFailure(ValueError):
    def __init__(self, code):
        self.code = code if isinstance(code,str) and code in ERRORS else 'creation_failed'
        super().__init__(self.code)

def safe_error(error, step):
    if isinstance(error, CreationFailure): return error.code
    if isinstance(error, ValueError) and str(error) in ERRORS: return str(error)
    if isinstance(error, subprocess.TimeoutExpired) and step in ('checking_socks', 'checking_exit'):
        return 'proxy_check_timeout'
    return DEFAULT_ERRORS.get(step, 'creation_failed')
