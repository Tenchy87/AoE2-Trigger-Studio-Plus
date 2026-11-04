from services.commands.base_command import Command


class DeleteLogicObjectCommand(Command):
    def __init__(
        self,
        trigger,
        kind,
        logic_object,
        index,
        description,
    ):
        self.selected_trigger = trigger
        self.kind = kind
        self.logic_object = logic_object
        self.index = index
        self.description = description
        self.selected_logic_object = None

    def _collection(self):
        if self.kind == "condition":
            return self.selected_trigger.conditions
        if self.kind == "effect":
            return self.selected_trigger.effects
        raise ValueError(f"Unsupported logic kind: {self.kind}")

    def redo(self):
        collection = self._collection()
        if self.logic_object in collection:
            collection.remove(self.logic_object)
        self.selected_logic_object = None

    def undo(self):
        collection = self._collection()
        if self.logic_object in collection:
            collection.remove(self.logic_object)
        insertion_index = min(self.index, len(collection))
        collection.insert(insertion_index, self.logic_object)
        self.selected_logic_object = self.logic_object
