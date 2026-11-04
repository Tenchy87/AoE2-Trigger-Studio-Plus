from services.commands.base_command import Command


class ChangeConditionTypeCommand(Command):
    def __init__(
        self,
        trigger,
        old_condition,
        index,
        condition_type,
        condition_id,
        condition_kwargs,
        condition_label,
    ):
        self.selected_trigger = trigger
        self.old_condition = old_condition
        self.index = index
        self.condition_type = condition_type
        self.condition_id = condition_id
        self.condition_kwargs = dict(condition_kwargs)
        self.condition_label = condition_label
        self.new_condition = None
        self.selected_logic_object = None
        self.description = f"Change Condition Type to {condition_label}"

    def _create_condition(self):
        if self.condition_type == "timer":
            return self.selected_trigger.new_condition.timer(
                **self.condition_kwargs
            )
        return self.selected_trigger._add_condition(
            self.condition_id,
            **self.condition_kwargs,
        )

    def _replace(self, remove_object, insert_object):
        conditions = self.selected_trigger.conditions
        if remove_object in conditions:
            conditions.remove(remove_object)
        if insert_object in conditions:
            conditions.remove(insert_object)
        insertion_index = max(0, min(self.index, len(conditions)))
        conditions.insert(insertion_index, insert_object)
        self.selected_logic_object = insert_object

    def redo(self):
        if self.new_condition is None:
            self.new_condition = self._create_condition()
        self._replace(self.old_condition, self.new_condition)

    def undo(self):
        if self.new_condition is None:
            return
        self._replace(self.new_condition, self.old_condition)
