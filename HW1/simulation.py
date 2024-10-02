import argparse
import json
import queue
import copy

logs = []
insts = []
# processor hardware states
pc= 0
p_reg= [0]*64
dir = []
#     'pc':0,
#     'op_code':0,
#     'opA':0,
#     'opB':0,
#     'dest':0,
e_flag = False
e_pc = 0
r_table = list(range(32))
f_list = list(range(32, 64))
busy_b = [False] * 64
act_list = []
int_q = []


class ShiftRegister:
    def __init__(self):
        self.pipeline_registers = [[]] * 2
    def shift_in(self, column: list):
        self.pipeline_registers.append(column)
    def shift_out(self):
        return self.pipeline_registers.pop(0)
shift_register = ShiftRegister()

# the copies of processor hardware states
pc_copy = None
p_reg_copy = None
dir_copy = None
e_flag_copy = None
e_pc_copy = None
r_table_copy = None
f_list_copy = None
busy_b_copy = None
act_list_copy = None
int_q_copy = None






def decodeInstruction(inst):
    global pc_copy
    parts = inst.split()
    op_code = parts[0]
    dest = int(parts[1].strip(',').replace('x', ''))
    opA = int(parts[2].strip(',').replace('x', ''))
    is_opB_immediate = False
    if op_code == 'addi':
        op_code = 'add'
        opB = int(parts[3])  # immediate value
        is_opB_immediate = True
    else:  # 'add'
        opB = int(parts[3].replace('x', ''))
    return {
        'pc': pc_copy,
        'op_code': op_code,
        'opA': opA,
        'opB': opB,
        'dest': dest,
        'is_opB_immediate': is_opB_immediate
    }


def parseInstructions(input_path):
    global insts
    with open(input_path, 'r') as file:
        insts = json.load(file)
    
def dumpStateIntoLog():
    global pc, p_reg, dir, e_flag, e_pc, r_table, f_list, busy_b, act_list, int_q
    # create a dictionary with the current state of the processor
    state = {
        'PC': pc,
        'PhysicalRegisterFile': p_reg,
        'DecodedPCs' : [d['pc'] for d in dir],
        'Exception': e_flag,
        'ExceptionPC': e_pc,
        'RegisterMapTable': r_table,
        'FreeList': f_list,
        'BusyBitTable': busy_b,
        'ActiveList': act_list,
        'IntegerQueue': int_q
    }
    logs.append(state)

def saveLog(output_path):
    global logs
    with open(output_path, 'w') as file:
        json.dump(logs, file)
    
def propagate():
    global pc, p_reg, dir, e_flag, e_pc, r_table, f_list, busy_b, act_list, int_q
    global pc_copy, p_reg_copy, dir_copy, e_flag_copy, e_pc_copy, r_table_copy, f_list_copy, busy_b_copy, act_list_copy, int_q_copy
    global insts
    global shift_register
    # ---------------make a copy of all processor state
    pc_copy = pc
    p_reg_copy = p_reg.copy()
    dir_copy = copy.deepcopy(dir)
    e_flag_copy = e_flag
    e_pc_copy = e_pc
    r_table_copy = r_table.copy()
    f_list_copy = f_list.copy()
    busy_b_copy = busy_b.copy()
    act_list_copy = copy.deepcopy(act_list)
    int_q_copy = copy.deepcopy(int_q)

    # ----------------forwarding path
    updated_registers = []
    update_values = []
    exception_pcs = []
    done_pcs = []

    # ----------------execution 2nd stage
    # I moved the execution 2nd stage to the front, because the forwarding path is driven by this stage
    # and therefore should be computed first
 
    incoming_insts = shift_register.shift_out()
    if (e_flag):
        incoming_insts = []
    for inst in incoming_insts:
        opa = inst['OpAValue']
        opb = inst['OpBValue']
        result = None
        has_exception = False
        match inst['OpCode']:
            case 'add':
                result = opa + opb
            case 'addi':
                result = opa + opb  # assuming opb is the immediate value
            case 'sub':
                result = opa - opb
            case 'mulu':
                result = opa * opb
            case 'divu':
                if opb != 0:  # prevent division by zero
                    result = opa // opb
                else:
                    has_exception = True
            case 'remu':
                if opb != 0:  # prevent division by zero
                    result = opa % opb
                else:
                    has_exception = True
            case _:
                raise Exception("Unknown opcode")
        # store the results in the forwarding path
        done_pcs.append(inst['PC'])
        if has_exception:
            exception_pcs.append(inst['PC'])
        else:
            updated_registers.append(inst['DestRegister'])
            result = result % (2**64)  # truncate to 32 bits
            update_values.append(result)

    # ----------------commit
    # I moved the commit stage to the front, since the commit stage also manages the active list and free list, and its changes should be seen by the rename stage,
    # as stated in the requirements
            
    if (e_flag):
        #exception recovering, (does it make sense to update the renaming table at commit stage?)
        if not act_list:
            e_flag_copy = False
        for i in range(4):
            if not act_list_copy:
                break
            else:
                act_list_entry = act_list_copy.pop()
                log_dest = act_list_entry['LogicalDestination']
                old_dest = act_list_entry['OldDestination']
                f_list_copy.append(r_table_copy[log_dest])
                busy_b_copy[r_table_copy[log_dest]] = False
                r_table_copy[log_dest] = old_dest
                
    else:
        # retire instructions
        for i in range(4):
            if not act_list_copy:
                break
            elif act_list_copy[0]["Exception"]:
                e_flag_copy = True
                e_pc_copy = act_list_copy[0]["PC"]
                break
            elif act_list_copy[0]["Done"]:
                retired = act_list_copy.pop(0)
                f_list_copy.append(retired["OldDestination"])
            else: # encounter an instruction that's not done yet
                break
    # I switched the sequence between retire instruction and update the active list, because the updates fron the forwarding path shouldn't be visible until next cycle
    # update the active list according to forwarding path
    for act_entry in act_list_copy:
        if act_entry['PC'] in done_pcs:
            act_entry['Done'] = True
        if act_entry['PC'] in exception_pcs:
            act_entry['Exception'] = True



    # ---------------check if there's back pressure
    b_pressure = False
    l = len(dir)
    if (len(f_list_copy) < l or l + len(act_list_copy) > 32): # read from a copy! because there's combinational path between write and read port
        b_pressure = True
    
    # ---------------Fetch and Decode
    
    # fetch and decode shoud react fast enough to exception, stop fetching the same cycle as the exceoption is commited
    if (not b_pressure) and (not e_flag_copy):
        dir_copy = []
        for i in range(4):
            
            if insts:
                inst = insts.pop(0)
                dir_copy.append(decodeInstruction(inst))
                pc_copy += 1
    if (e_flag_copy):
        dir_copy = []
        pc_copy = 0x10000

    # ----------------Issue
    if (e_flag_copy):
        int_q_copy = []
    # update the integer queue according to the forwarding path
    for int_q_entry in int_q_copy:
        for r, v in zip(updated_registers,update_values):
            if (not int_q_entry['OpAIsReady']) and int_q_entry['OpARegTag'] == r:
                int_q_entry['OpAIsReady'] = True
                int_q_entry['OpAValue'] = v
            if (not int_q_entry['OpBIsReady']) and int_q_entry['OpBRegTag'] == r:
                int_q_entry['OpBIsReady'] = True
                int_q_entry['OpBValue'] = v
    # issue the instruction
    i = 0
    issed_counter = 0
    issued_entrys = []
    while i < len(int_q_copy):
        entry = int_q_copy[i]
        if (entry['OpAIsReady'] and entry['OpBIsReady']):
            # issue the instruction
            issued_entrys.append(int_q_copy.pop(i))
            issed_counter += 1
            if issed_counter == 4:
                break
        else:
            i += 1
    shift_register.shift_in(issued_entrys)
    # switched the sequence of R&D and Issue, because an update to the integer queue from the R&D stage shouldn't be visible until the next stage
    # plus, its repetitive to update the new entry again in the cycle that its been created

    # ---------------Rename and Dispatch
    # update according to the forwarding path, so that the register read later will produce the newest result
    if not e_flag:
        for r, v in zip(updated_registers, update_values):
            p_reg_copy[r] = v
            if not busy_b[r]:
                raise Exception("try to update a Busy bit that's already False!")
            busy_b_copy[r] = False
    if not b_pressure and not e_flag:
        for i in range(len(dir)):

            # read register A mapping, and potentianlly read register value
            opA = r_table_copy[dir[i]['opA']]
            opA_rdy = not busy_b_copy[opA]  # read from a copy! should instead check the value from the forwarding path
            opA_val = None
            if (opA_rdy):
                opA_val = p_reg_copy[opA] # read from a copy! should instead check the value from the forwarding path
            # read register B mapping, and potentianlly read register value
            opB = None
            if dir[i]['is_opB_immediate']:
                opB_val = dir[i]['opB']
                opB_rdy = True
            else:
                opB = r_table_copy[dir[i]['opB']]
                opB_rdy = not busy_b_copy[opB] # read from a copy! should instead check the value from the forwarding path
                opB_val = None
                if (opB_rdy):
                    opB_val = p_reg_copy[opB] # read from a copy! should instead check the value from the forwarding path
            # remap the dest register, update the register mapping table and free list
            log_dest = dir[i]['dest']
            dest = f_list_copy.pop(0) 
            busy_b_copy[dest] = True
            old_dest = r_table_copy[log_dest]
            r_table_copy[log_dest] = dest

            int_q_copy.append({
                "DestRegister": dest,
                "OpAIsReady": opA_rdy,
                "OpARegTag": opA,
                "OpAValue": opA_val,
                "OpBIsReady": opB_rdy,
                "OpBRegTag": opB,
                "OpBValue": opB_val,
                "OpCode": dir[i]['op_code'],
                "PC": dir[i]['pc']
            })

            act_list_copy.append({
               "Done": False,
               "Exception": False,
               "LogicalDestination": log_dest,
               "OldDestination": old_dest,
               "PC": dir[i]['pc'],
            })






def latch():
    global pc, p_reg, dir, e_flag, e_pc, r_table, f_list, busy_b, act_list, int_q
    global pc_copy, p_reg_copy, dir_copy, e_flag_copy, e_pc_copy, r_table_copy, f_list_copy, busy_b_copy, act_list_copy, int_q_copy
    # update the processor state
    pc = pc_copy
    p_reg = p_reg_copy
    dir = dir_copy
    e_flag = e_flag_copy
    e_pc = e_pc_copy
    r_table = r_table_copy
    f_list = f_list_copy
    busy_b = busy_b_copy
    act_list = act_list_copy
    int_q = int_q_copy


def main(input_path, output_path):
    global insts, act_list, e_flag
    # convert path to file pointer
    parseInstructions(input_path)
    #print(insts)
    dumpStateIntoLog()


    # 2. the loop for cycle-by-cycle iterations.
    exception_recovering = False
    #counter = 0
    while insts or act_list or exception_recovering:
        # do propagation
        # if you have multiple modules, propagate each of them
        propagate()
        # advance clock, start next cycle
        latch()
        # dump the state
        dumpStateIntoLog()
        if(e_flag):
            # print("exception at cycle{}".format(counter))
            exception_recovering = True
        if(exception_recovering):
            if not e_flag:
                # print("exception recovered at cycle{}".format(counter))
                break
        # print("cycle{} done".format(counter))
        # counter += 1
        # if counter > 100:
        #     break

    # 3. save the output JSON log
    saveLog(output_path)


if __name__ == "__main__":



    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument('input_path', type=str, help='Input file path')
    parser.add_argument('output_path', type=str, help='Output file path')

    args = parser.parse_args()

    main(args.input_path, args.output_path)
