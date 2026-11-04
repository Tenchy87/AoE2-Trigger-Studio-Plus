from services.commands.base_command import Command


class MoveLogicObjectCommand(Command):
    def __init__(
        self,
        trigger,
        kind,
        logic_object,
        old_index,
        new_index,
        description,
    ):
        self.selected_trigger = trigger
        self.kind = kind
        self.logic_object = logic_object
        self.old_index = old_index
        self.new_index = new_index
        self.description = description
        self.selected_logic_object = logic_object

    def _collection(self):
        if self.kind == "condition":
            return self.selected_trigger.conditions
        if self.kind == "effect":
            return self.selected_trigger.effects
        raise ValueError(f"Unsupported logic kind: {self.kind}")

    def _move_to(self, target_index):
        collection = self._collection()
        if self.logic_object not in collection:
            raise ValueError("The logic object is no longer in the trigger.")

        collection.remove(self.logic_object)
        target_index = max(0, min(target_index, len(collection)))
        collection.insert(target_index, self.logic_object)
        self.selected_logic_object = self.logic_object

    def undo(self):
        self._move_to(self.old_index)

    def redo(self):
        self._move_to(self.new_index)
