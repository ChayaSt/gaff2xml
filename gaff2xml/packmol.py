import numpy as np
import shutil
import os
import mdtraj as md
from mdtraj.utils import enter_temp_directory
import tempfile
from distutils.spawn import find_executable

PACKMOL_PATH = find_executable("packmol")

HEADER_TEMPLATE = """
# Mixture 

tolerance %f
filetype pdb
output %s
add_amber_ter

"""

BOX_TEMPLATE = """
structure %s
  number %d 
  inside box 0. 0. 0. %f %f %f
end structure
"""
PROTEIN_TEMPLATE = """
structure %s
    number %d
    center
    fixed 0.0 0.0 0.0 0.0 0.0 0.0 
end structure

"""

TORUS_TEMPLATE = """
structure %s
    number %d
    atoms %d
        under plane 0.0 0.0 1.0 %f
        over plane 0.0 0.0 1.0 -%f
        outside sphere 0.0 0.0 0.0 %f
    end atoms

    atoms %d
        under plane 0.0 0.0 1.0 %f
        over plane 0.0 0.0 1.0 -%f
        inside sphere 0.0 0.0 0.0 %f
    end atoms
end structure
"""

def pack_box(pdb_filenames, n_molecules_list, tolerance=2.0, box_size=None):
    """Run packmol to generate a box containing a mixture of molecules.

    Parameters
    ----------
    pdb_filenames : list(str)
        List of pdb filenames for each component of mixture.
    n_molecules_list : list(int)
        The number of molecules of each mixture component.
    tolerance : float, optional, default=2.0
        The mininum spacing between molecules during packing.  In ANGSTROMS!
    box_size : float, optional
        The size of the box to generate.  In ANGSTROMS.
        Default generates boxes that are very large for increased stability.
        May require extra time for energy minimization and equilibration.

    Returns
    -------
    trj : MDTraj.Trajectory
        Single frame trajectory with mixture box.

    Notes
    -----
    Be aware that MDTraj uses nanometers internally, but packmol uses angstrom
    units.  The present function takes `tolerance` and `box_size` in 
    angstrom units, but the output trajectory will have data in nm.  
    Also note that OpenMM is pretty picky about the format of unit cell input, 
    so use the example in tests/test_packmol.py to ensure that you do the right thing.

    """    
    assert len(pdb_filenames) == len(n_molecules_list), "Must input same number of pdb filenames as num molecules"
    
    if PACKMOL_PATH is None:
        raise(IOError("Packmol not found, cannot run pack_box()"))
    
    output_filename = tempfile.mktemp(suffix=".pdb")

    # approximating volume to initialize  box
    if box_size is None:
        box_size = approximate_volume(pdb_filenames, n_molecules_list)    

    header = HEADER_TEMPLATE % (tolerance, output_filename)
    for k in range(len(pdb_filenames)):
        filename = pdb_filenames[k]
        n_molecules = n_molecules_list[k]
        header = header + BOX_TEMPLATE % (filename, n_molecules, box_size, box_size, box_size)
    
    pwd = os.getcwd()
    
    print(header)
    
    packmol_filename = "packmol_input.txt"
    packmol_filename = tempfile.mktemp(suffix=".txt")
    
    file_handle = open(packmol_filename, 'w')
    file_handle.write(header)
    file_handle.close()
    
    print(header)

    os.system("%s < %s" % (PACKMOL_PATH, packmol_filename)) 

    trj = md.load(output_filename)

    assert trj.topology.n_chains == sum(n_molecules_list), "Packmol error: molecules missing from output"
    
    #Begin hack to introduce bonds for the MISSING CONECT ENTRIES THAT PACKMOL FAILS TO WRITE
    
    top, bonds = trj.top.to_dataframe()

    trj_i = [md.load(filename) for filename in pdb_filenames]
    bonds_i = [t.top.to_dataframe()[1] for t in trj_i]

    offset = 0
    bonds = []
    for i in range(len(pdb_filenames)):
        n_atoms = trj_i[i].n_atoms
        for j in range(n_molecules_list[i]):        
            bonds.extend(bonds_i[i] + offset)
            offset += n_atoms

    bonds = np.array(bonds)
    trj.top = md.Topology.from_dataframe(top, bonds)
    
    trj.unitcell_vectors = np.array([np.eye(3)]) * box_size / 10.
    
    return trj

def approximate_volume(pdb_filenames, n_molecules_list):
    rho = 2.2
    volume = 0.0 # in cubic angstroms
    for k, (pdb_file) in enumerate(pdb_filenames):
        molecule_volume = 0.0
        molecule_trj = md.load(pdb_filenames[k])
        for atom in molecule_trj.topology.atoms:
            if atom.element.symbol == 'H':
                molecule_volume += 5.0 # approximated from bondi radius = 1.06 angstroms
            else:
                molecule_volume += 15.0 # approximated from bondi radius of carbon = 1.53 angstroms
        volume += molecule_volume * n_molecules_list[k]
    box_size = volume**(1.0/3.0) * rho
    return box_size

def build_torus(pdb_filenames, n_molecule_list, plane, radius, head, tail, tolerance=2.5):
    """Run packmol to generate a box containing a mixture of molecules.

    Parameters
    ----------
    pdb_filenames : list(str)
        List of pdb filenames for each component of mixture.
    n_molecules_list : list(int)
        The number of molecules of each mixture component.
    plane: (int) height of sphere cut off
    radius: list(int) inner and outer radius of sphere to constrain detergent
    head: atom number(int) of detergent to point out of torus
    tail: atom number(int) of detergent to point towards protein 
    tolerance : float, optional, default=2.5
        The mininum spacing between molecules during packing.  In ANGSTROMS!

    Returns
    -------
    trj : MDTraj.Trajectory
        Single frame trajectory with protein inside micelle that's shaped as a torus.

    Notes
    -----
    Be aware that MDTraj uses nanometers internally, but packmol uses angstrom
    units.  The present function takes `tolerance` and `box_size` in 
    angstrom units, but the output trajectory will have data in nm.  
    Also note that OpenMM is pretty picky about the format of unit cell input, 
    so use the example in tests/test_packmol.py to ensure that you do the right thing.

    """    
    assert len(pdb_filenames) == len(n_molecules_list), "Must input same number of pdb filenames as num molecules"
    
    if PACKMOL_PATH is None:
        raise(IOError("Packmol not found, cannot run pack_box()"))
    
    output_filename = tempfile.mktemp(suffix=".pdb")

    header = HEADER_TEMPLATE % (tolerance, output_filename)
    header = header + PROTEIN_TEMPLATE % (filname[0], n_molecules[0])
    for k in range(1,len(pdb_filenames)):
        filename = pdb_filenames[k]
        n_molecules = n_molecules_list[k]
        header = header + TORUS_TEMPLATE % (filename, n_molecules, head, plane, plane, radius[1], tail, plane, plane, radius[0])
    
    pwd = os.getcwd()
    
    print(header)
    
    packmol_filename = "packmol_input.txt"
    packmol_filename = tempfile.mktemp(suffix=".txt")
    
    file_handle = open(packmol_filename, 'w')
    file_handle.write(header)
    file_handle.close()
    
    print(header)

    os.system("%s < %s" % (PACKMOL_PATH, packmol_filename)) 
     
    trj = md.load(output_filename)

    assert trj.topology.n_chains == sum(n_molecules_list), "Packmol error: molecules missing from output"
    
    return trj
