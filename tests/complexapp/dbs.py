from dbs import backup_registry

from .models import (
    Branch,
    EditingAssignment,
    Employee,
    EmployeeProfile,
    Keyword,
    Publisher,
    Review,
    Series,
    Volume,
    Writer,
)

backup_registry.register(Publisher)
backup_registry.register(Branch)
backup_registry.register(Employee)
backup_registry.register(EmployeeProfile)
backup_registry.register(Writer)
backup_registry.register(Keyword)
backup_registry.register(Series)
backup_registry.register(Volume)
backup_registry.register(EditingAssignment)
backup_registry.register(Review)
