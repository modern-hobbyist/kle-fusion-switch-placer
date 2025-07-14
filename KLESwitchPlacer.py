# Author: Charlie Steenhagen
# Fusion 360 Add-In: KLE Switch Placer (supports rotation)

import adsk.core, adsk.fusion, adsk.cam, traceback, json, os, math

_app = None
_ui = None
_handlers = []


class KLEKey:
    def __init__(self):
        self.x = 0
        self.y = 0
        self.x2 = 0
        self.y2 = 0
        self.width = 1
        self.height = 1
        self.width2 = 0
        self.height2 = 0
        self.rotation_angle = 0
        self.rotation_x = 0
        self.rotation_y = 0
        self.nub = False
        self.stepped = False
        self.decal = False
        self.labels = []
        self.profile = None
        self.color = None

    def copy(self):
        clone = KLEKey()
        clone.__dict__ = self.__dict__.copy()
        return clone


def deserialize_kle_layout(rows):
    keys = []
    current = KLEKey()

    current_row = 0
    current_col = 0

    cursor_x = 0
    cursor_y = 0

    for r, row in enumerate(rows):
        if isinstance(row, dict) and r == 0:
            continue  # skip metadata row

        if isinstance(row, list):
            col = 0
            for item in row:
                if isinstance(item, dict):
                    # Handle layout modifiers
                    if 'r' in item:
                        current.rotation_angle = item['r']
                        current_col = 0
                        current_row = 0
                        cursor_x = 0
                        cursor_y = 0
                    if 'rx' in item:
                        current.rotation_x = item['rx']
                        current_col = 0
                        cursor_x = 0
                    if 'ry' in item:
                        current.rotation_y = item['ry']
                        current_row = 0
                        cursor_y = 0
                    if 'x' in item:
                        cursor_x += item['x']
                    if 'y' in item:
                        cursor_y += item['y']
                    if 'w' in item:
                        current.width = current.width2 = item['w']
                    if 'h' in item:
                        current.height = current.height2 = item['h']
                    if 'x2' in item:
                        current.x2 = item['x2']
                    if 'y2' in item:
                        current.y2 = item['y2']
                    if 'w2' in item:
                        current.width2 = item['w2']
                    if 'h2' in item:
                        current.height2 = item['h2']
                    if 'n' in item:
                        current.nub = item['n']
                    if 'l' in item:
                        current.stepped = item['l']
                    if 'd' in item:
                        current.decal = item['d']
                    if 'p' in item:
                        current.profile = item['p']
                    if 'c' in item:
                        current.color = item['c']
                elif isinstance(item, str):
                    key = current.copy()
                    key.labels = item.split('\n')
                    key.width2 = key.width2 or key.width
                    key.height2 = key.height2 or key.height

                    # Determine key position
                    if current.rotation_angle != 0 or current.rotation_x != 0 or current.rotation_y != 0:
                        key.x = current.rotation_x + cursor_x
                        key.y = current.rotation_y + cursor_y
                        cursor_x += key.width
                    else:
                        key.x = cursor_x
                        key.y = cursor_y
                        cursor_x += key.width

                    keys.append(key)

                    # Reset modifiers
                    current.width = 1
                    current.height = 1
                    current.width2 = 0
                    current.height2 = 0
                    current.x2 = 0
                    current.y2 = 0
                    current.nub = False
                    current.stepped = False
                    current.decal = False
            # End of row
            if current.rotation_angle != 0 or current.rotation_x != 0 or current.rotation_y != 0:
                cursor_x = 0
                cursor_y += 1
            else:
                cursor_x = 0
                cursor_y += 1

    return keys



def run(context):
    global _app, _ui
    _app = adsk.core.Application.get()
    _ui = _app.userInterface

    try:
        cmdDef = _ui.commandDefinitions.itemById('KLESwitchPlacerCmd')
        if not cmdDef:
            cmdDef = _ui.commandDefinitions.addButtonDefinition(
                'KLESwitchPlacerCmd',
                'KLE Switch Placer',
                'Places switches using a KLE layout'
            )

        onCommandCreated = KLECommandCreatedHandler()
        cmdDef.commandCreated.add(onCommandCreated)
        _handlers.append(onCommandCreated)

        panel = _ui.allToolbarPanels.itemById('SolidScriptsAddinsPanel')
        if not panel.controls.itemById('KLESwitchPlacerCmd'):
            panel.controls.addCommand(cmdDef)

    except:
        _ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))


def stop(context):
    try:
        panel = _ui.allToolbarPanels.itemById('SolidScriptsAddinsPanel')
        control = panel.controls.itemById('KLESwitchPlacerCmd')
        if control:
            control.deleteMe()

        cmdDef = _ui.commandDefinitions.itemById('KLESwitchPlacerCmd')
        if cmdDef:
            cmdDef.deleteMe()
    except:
        if _ui:
            _ui.messageBox('Stop Failed:\n{}'.format(traceback.format_exc()))


class KLECommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        cmd = args.command
        inputs = cmd.commandInputs

        inputs.addStringValueInput('kleFilePath', 'KLE JSON Path', '')
        inputs.itemById('kleFilePath').isReadOnly = True
        inputs.addBoolValueInput('selectKLEFile', 'Pick KLE JSON File', False, '', False)

        sel = inputs.addSelectionInput('switchComp', 'Switch Component', 'Select a component to place as the switch')
        sel.addSelectionFilter("Occurrences")
        sel.setSelectionLimits(1, 1)

        inputs.addValueInput('hSpacing', 'Horizontal Spacing (mm)', 'mm', adsk.core.ValueInput.createByReal(1.905))
        inputs.addValueInput('vSpacing', 'Vertical Spacing (mm)', 'mm', adsk.core.ValueInput.createByReal(1.905))

        onInputChanged = KLEInputChangedHandler()
        cmd.inputChanged.add(onInputChanged)
        _handlers.append(onInputChanged)

        onExecute = KLECommandExecuteHandler()
        cmd.execute.add(onExecute)
        _handlers.append(onExecute)


class KLEInputChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            inputs = args.firingEvent.sender.commandInputs
            changed = args.input

            if changed.id == 'selectKLEFile':
                fileDlg = _ui.createFileDialog()
                fileDlg.title = "Select KLE JSON file"
                fileDlg.filter = 'JSON files (*.json);;All files (*.*)'
                fileDlg.isMultiSelectEnabled = False

                if fileDlg.showOpen() == adsk.core.DialogResults.DialogOK:
                    inputs.itemById('kleFilePath').value = fileDlg.filename

        except:
            _ui.messageBox('InputChanged Failed:\n{}'.format(traceback.format_exc()))


class KLECommandExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs = args.firingEvent.sender.commandInputs
            kle_path = inputs.itemById('kleFilePath').value
            h_spacing = inputs.itemById('hSpacing').value
            v_spacing = inputs.itemById('vSpacing').value

            if not kle_path or not os.path.exists(kle_path):
                _ui.messageBox('KLE file not found or not selected.')
                return

            with open(kle_path, 'r') as f:
                kle_data = json.load(f)

            keys = deserialize_kle_layout(kle_data)

            switch_occ = inputs.itemById('switchComp').selection(0).entity
            if not isinstance(switch_occ, adsk.fusion.Occurrence):
                _ui.messageBox('Invalid switch component selected.')
                return

            switch_comp = switch_occ.component
            design = adsk.fusion.Design.cast(_app.activeProduct)
            root = design.rootComponent

            if switch_comp == root:
                _ui.messageBox('Cannot insert the root component into itself.')
                return

            switches_occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
            switches_occ.component.name = 'Switches'
            switches_comp = switches_occ.component

            for key in keys:
                angle_deg = key.rotation_angle
                angle_rad = math.radians(angle_deg)

                # Pivot in mm
                rx = key.rotation_x * h_spacing
                ry = key.rotation_y * v_spacing


                # Local key position (before rotation), relative to rotation origin
                local_x = (key.x - key.rotation_x) * h_spacing
                local_y = (key.y - key.rotation_y) * v_spacing
                local_x += (key.width * h_spacing) / 2
                local_y += (key.height * v_spacing) / 2

                # Final global position (translate back to global origin)
                final_x = rx + local_x
                final_y = ry + local_y

                transform = adsk.core.Matrix3D.create()
                transform.translation = adsk.core.Vector3D.create(final_x, -final_y, 0)

                if angle_deg != 0:
                    z_axis = adsk.core.Vector3D.create(0, 0, 1)
                    center = adsk.core.Point3D.create(rx, -ry, 0)
                    rotation = adsk.core.Matrix3D.create()
                    rotation.setToRotation(-angle_rad, z_axis, center)
                    transform.transformBy(rotation)

                switches_comp.occurrences.addExistingComponent(switch_comp, transform)


            switch_occ.isLightBulbOn = False

        except:
            _ui.messageBox('Execute Failed:\n{}'.format(traceback.format_exc()))
