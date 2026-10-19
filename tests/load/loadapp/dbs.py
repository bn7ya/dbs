from dbs import backup_registry
from tests.load.loadapp.models import Customer, Order

backup_registry.register(Customer)
backup_registry.register(Order)
