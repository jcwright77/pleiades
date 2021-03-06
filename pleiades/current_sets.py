from abc import ABCMeta, abstractmethod, abstractproperty
from collections import Iterable
from warnings import warn, simplefilter
import math
import numpy as np
from scipy.special import ellipk, ellipe
from matplotlib.path import Path
import matplotlib.patches as patches

from pleiades.fields import FieldsOperator
import pleiades.checkvalue as cv
from pleiades.transforms import rotate


class CurrentFilamentSet(metaclass=ABCMeta):
    """Set of locations that have the same current value.

    A CurrentFilamentSet represents a set of axisymmetric current centroids with
    associated current weights to describe the current ratios between all the
    centroids. In addition, a CurrentFilamentSet implements the Green's function
    functionality for computing magnetic fields and flux on an R-Z mesh. A
    CurrentFilamentSet is not intended to be instatiated directly, but serves as
    the base class for all concrete current set classes and defines the
    minimum functional interface and protocols of a current set. Lastly a
    matplotlib.patches.PathPatch object is associated with each
    CurrentFilamentSet for ease in plotting and verifying device geometry.

    Parameters
    ----------
    current : float, optional
        The current to be used for calculating fields from the Green's
        functions. Defaults to 1 amp.
    weights : iterable, optional
        The weights for all the current locations. The current weight is
        effectively a current multiplier for a given position that is
        incorporated into the Green's function. This enables having both
        positive and negative currents in an object at the same time as well as
        current profile shaping in the case of permanent magnets. Defaults to
        1 for every location.
    patch_kw : dict
        Dictionary of any matplotlib.patches.Patch keyword arguments. No type
        checking is performed on these inputs they are simply assigned to the
        patch_kw attribute.
    **kwargs
        Any keyword arguments intended to be passed to FieldsOperator object
        using cooperative inheritance.

    Attributes
    ----------
    current : float
        The current to be used for calculating fields from the Green's
        functions. Defaults to 1 amp.
    weights : iterable
        The weights for all the current locations. The current weight is
        effectively a current multiplier for a given position that is
        incorporated into the Green's function. This enables having both
        positive and negative currents in an object at the same time as well as
        current profile shaping in the case of permanent magnets. Defaults to
        1 for every location.
    npts : int
        Integer for the number of current filaments in this CurrentFilamentSet
        (read-only).
    rz_pts : ndarray
        An Nx2 array representing (R, Z) coordinates for current centroids.
        Units are meters and the coordinate system is cylindrical (read-only)
    rzw : np.ndarray
        An Nx3 array whos columns describe the current centroid radial
        coordinate (R), vertical coordinate (Z), and current weight (W) for each
        filament in the CurrentFilamentSet (read-only).
    total_current : float
        The total current being carried in the filament set. This is equal to
        the current times the sum of the weights.
    patch_kw : dict
        A dictionary of valid matplotlib.patches.Patch keyword arguments

    """

    def __init__(self, current=1., weights=None, patch_kw=None, **kwargs):
        self.current = current
        if weights is None:
            self._weights = np.ones(self.npts)
        else:
            self._weights = weights
        self.patch_kw = patch_kw
        super().__init__(**kwargs)

    def __repr__(self):
        string = 'CurrentFilamentSet\n'
        string += '{0: >16}  {1}\n'.format('Class:', self.__class__)
        string += '{0: >16}  {1:.6e} amps\n'.format('Current:', self.current)
        string += '{0: >16}  {1}\n'.format('N Filaments:', self.npts)
        string += '{0: >16}  {1:.6e} amps\n'.format('Total Current:',
                                                    self.total_current)
        for i, (r, z, w) in enumerate(self.rzw):
            rzwtxt = '[{0:.6e}, {1:.6e}, {2:.6e}]'.format(r, z, w)
            if i == 0:
                string += '{0: >16}  {1}\n'.format('R, Z, W:', rzwtxt)
            else:
                string += '{0: >16}  {1}\n'.format('', rzwtxt)

        return string

    @abstractproperty
    def npts(self):
        pass

    @abstractproperty
    def rz_pts(self):
        pass

    @abstractproperty
    def patch(self):
        pass

    @property
    def current(self):
        return self._current

    @property
    def weights(self):
        return self._weights

    @property
    def rzw(self):
        rzw = np.empty((self.npts, 3))
        rzw[:, 0:2] = self.rz_pts
        rzw[:, 2] = self.weights
        return rzw

    @property
    def total_current(self):
        return self.current*np.sum(self.weights)

    @property
    def _markers(self):
        cw = self.current*self.weights
        cw[np.abs(cw) < cv._ATOL] = 0
        return ['' if cwi == 0 else 'x' if cwi > 0 else 'o' for cwi in cw]

    @current.setter
    def current(self, current):
        self._current = current

    @weights.setter
    @cv.flag_greens_on_set
    def weights(self, weights):
        self._weights = np.asarray(weights)

    @total_current.setter
    def total_current(self, total_current):
        self.current = total_current / np.sum(self.weights)

    @abstractmethod
    def translate(self, vector):
        """Translate the current group by the vector (dr, dz)

        Parameters
        ----------
        vector : iterable of float
            The displacement vector for the translation
        """

    @abstractmethod
    def rotate(self, angle, pivot=(0., 0.)):
        """Rotate the current group by a given angle around a specified pivot

        Parameters
        ----------
        angle : float
            The angle of the rotation in degrees as measured from the z axis
        pivot : iterable of float, optional
            The (R, Z) location of the pivot. Defaults to (0., 0.).
        """

    def simplify(self):
        """Create a single coil object from weighted sum of current centroids.
        """
        r0, z0 = np.mean(self.rz_pts, axis=0)
        current = self.total_current
        raise NotImplementedError

    def clone(self):
        """Create and return a copy of this coil"""
        raise NotImplementedError

    def plot(self, ax, plot_patch=True, **kwargs):
        """Plot the current locations for the CurrentGroup

        Parameters
        ----------
        ax : matplotlib.Axes object
            The axes object for plotting the current locations
        plot_patch : bool
            Whether to add the patch for this CurrentFilament to the axes.
        **kwargs : dict, optional
            Keyword arguments to pass to Current.plot method
        """
        if plot_patch:
            ax.add_patch(self.patch)

        markers = self._markers
        for i, (r, z, w) in enumerate(self.rzw):
            ax.plot(r, z, marker=markers[i], **kwargs)


class ArbitraryPoints(CurrentFilamentSet, FieldsOperator):
    """A set of arbitrary points in the R-Z plane with the same current

    Parameters
    ----------
    rzpts : np.ndarray
        An Nx2 array of (R,Z) locations for the filaments that comprise this
        set.
    **kwargs
        Any valid keyword arguments for CurrentFilamentSet.

    Attributes
    ----------
    """

    def __init__(self, rz_pts, **kwargs):
        self._rz_pts = np.asarray(rz_pts)
        self._angle = 0.
        super().__init__(**kwargs)

    @property
    def npts(self):
        return len(self.rz_pts)

    @property
    def rz_pts(self):
        return self._rz_pts

    @property
    def patch(self):
        return None

    def translate(self, vector):
        self._rz_pts += np.array(vector)
        self._uptodate = False

    def rotate(self, angle, pivot=(0., 0.)):
        self._angle += angle
        angle = math.pi*angle / 180
        c, s = np.cos(angle), np.sin(angle)
        rotation = np.array([[c, -s], [s, c]])
        self._rz_pts = (self.rz_pts - pivot) @ rotation + np.asarray(pivot)
        self._uptodate = False


class RectangularCoil(CurrentFilamentSet, FieldsOperator):
    """A rectangular cross section coil in the R-Z plane

    Parameters
    ----------
    r0 : float
        The R location of the centroid of the coil
    z0 : float
        The Z location of the centroid of the coil
    nr : float, optional
        The number of current filaments in the R direction. Defaults to 10.
    nz : float, optional
        The number of current filaments in the Z direction. Defaults to 10.
    dr : float, optional
        The distance between current filaments in the R direction. Defaults to
        0.01 m
    dz : float, optional
        The distance between current filaments in the Z direction. Defaults to
        0.01 m
    nhat : iterable of float, optional
        A vector of (dr, dz) representing the orientation of the coil and the
        'local z direction'. This is the direction which applies to nz and dz
        when constructing current filament locations. The 'r' direction is found
        by the relation nhat x phi_hat = rhat. Defaults to (0, 1) meaning the
        local z axis is aligned with the global z axis and likewise for the r
        axis.
    **kwargs
        Any valid keyword arguments for CurrentFilamentSet.

    Attributes
    ----------
    r0 : float
        The R location of the centroid of the Coil
    z0 : float
        The Z location of the centroid of the Coil
    centroid : np.array
        Helper attribue for the R, Z location of the centroid of the Coil
    nr : float
        The number of current filaments in the R direction. Defaults to 10.
    nz : float
        The number of current filaments in the Z direction. Defaults to 10.
    dr : float
        The distance between current filaments in the R direction. Defaults to
        0.1 m
    dz : float
        The distance between current filaments in the Z direction. Defaults to
        0.1 m
    angle : float
        An angle in degrees representing the rotation of the coil and the 'local
        z direction' with respect to the global z axis. This is the direction
        which applies to nz and dz when constructing current filament locations.
        Defaults to 0 meaning the local z axis is aligned with the global z
        axis.
    verts : np.ndarray
        A 4x2 np.array representing the 4 vertices of the coil (read-only).
    area : float
        The area of the coil in m^2 (read-only).
    current_density : float
        The current density in the coil. This is equal to the total current
        divided by the area (read-only).
    """

    _codes = [Path.MOVETO,
              Path.LINETO,
              Path.LINETO,
              Path.LINETO,
              Path.CLOSEPOLY]

    def __init__(self, r0=1., z0=0., nr=1, nz=1, dr=0.1, dz=0.1,
                 angle=0., **kwargs):
        self._r0 = r0
        self._z0 = z0
        self._nr = nr
        self._nz = nz
        self._dr = dr
        self._dz = dz
        self._angle = angle
        super().__init__(**kwargs)

    @property
    def r0(self):
        return self._r0

    @property
    def z0(self):
        return self._z0

    @property
    def centroid(self):
        return np.array([self.r0, self.z0])

    @property
    def nr(self):
        return self._nr

    @property
    def nz(self):
        return self._nz

    @property
    def dr(self):
        return self._dr

    @property
    def dz(self):
        return self._dz

    @property
    def angle(self):
        return self._angle

    @property
    def npts(self):
        return self.nr*self.nz

    @property
    def rz_pts(self):
        # Compute the rz_pts locations from this coil's internal parameters
        r0, z0 = self.centroid
        nr, dr, nz, dz = self.nr, self.dr, self.nz, self.dz
        rl, ru = r0 - dr*(nr - 1)/2, r0 + dr*(nr - 1)/2
        zl, zu = z0 - dz*(nz - 1)/2, z0 + dz*(nz - 1)/2
        r = np.linspace(rl, ru, nr)
        z = np.linspace(zl, zu, nz)
        rz_pts = np.array([(ri, zi) for ri in r for zi in z])
        if np.isclose(self.angle, 0):
            return rz_pts
        return rotate(rz_pts, self.angle, pivot=(r0, z0))

    @property
    def patch(self):
        return patches.PathPatch(Path(self._verts, self._codes))

    @property
    def _verts(self):
        # Get indices for 4 corners of current filament array
        nr, dr, nz, dz = self.nr, self.dr, self.nz, self.dz
        idx = np.array([0, nz - 1, nr*nz - 1, (nr - 1)*nz, 0])
        verts = self.rz_pts[idx, :]

        # Get correction vector to account for half width of filaments
        hdr, hdz = self.dr/2, self.dz/2
        dverts = np.array([[-hdr, -hdz],
                           [-hdr, hdz],
                           [hdr, hdz],
                           [hdr, -hdz],
                           [-hdr, -hdz]])

        if not np.isclose(self.angle, 0):
            dverts = rotate(dverts, self.angle)

        return verts + dverts

    @property
    def area(self):
        return self.nr*self.dr*self.nz*self.dz

    @property
    def current_density(self):
        return self.total_current / self.area

    @r0.setter
    @cv.flag_greens_on_set
    def r0(self, r0):
        self._r0 = r0

    @z0.setter
    @cv.flag_greens_on_set
    def z0(self, z0):
        self._z0 = z0

    @centroid.setter
    @cv.flag_greens_on_set
    def centroid(self, centroid):
        self._r0 = centroid[0]
        self._z0 = centroid[1]

    @nr.setter
    @cv.flag_greens_on_set
    def nr(self, nr):
        self._nr = nr

    @nz.setter
    @cv.flag_greens_on_set
    def nz(self, nz):
        self._nz = nz

    @dr.setter
    @cv.flag_greens_on_set
    def dr(self, dr):
        self._dr = dr

    @dz.setter
    @cv.flag_greens_on_set
    def dz(self, dz):
        self._dz = dz

    @angle.setter
    @cv.flag_greens_on_set
    def angle(self, angle):
        self._angle = angle

    def translate(self, vector):
        self.centroid += np.array(vector)

    def rotate(self, angle, pivot=(0., 0.)):
        self.angle += angle
        angle = math.pi*angle / 180
        c, s = np.cos(angle), np.sin(angle)
        rotation = np.array([[c, -s], [s, c]])
        self.centroid = (self.centroid - pivot) @ rotation + np.asarray(pivot)


class MagnetRing(CurrentFilamentSet, FieldsOperator):
    """A rectangular cross-section axisymmetric dipole magnet ring.

    A MagnetRing models a series of permanent dipole magnets placed
    axisymmetrically in a ring. The dipole magnet is modeled with anti-parallel
    surface currents on either side of the magnet.

    Parameters
    ----------
    r0 : float
        The R location of the centroid of the magnet ring
    z0 : float
        The Z location of the centroid of the magnet ring
    width : float, optional
        The width of the magnet. Defaults to 0.01 m.
    height : float, optional
        The height of the magnet. Defaults to 0.01 m.
    mu_hat : float, optional
        The angle of the magnetic moment of the magnet in degrees from the z
        axis. Defaults to 0 degrees clockwise from Z axis (i.e. north pole
        points in the +z direction).
    **kwargs
        Any valid keyword arguments for CurrentFilamentSet.

    Attributes
    ----------
    r0 : float
        The R location of the centroid of the Coil
    z0 : float
        The Z location of the centroid of the Coil
    centroid : np.array
        Helper attribue for the R, Z location of the centroid of the Coil
    width : float, optional
        The width of the magnet. Defaults to 0.01 m.
    height : float, optional
        The height of the magnet. Defaults to 0.01 m.
    mu_hat : float, optional
        The angle of the magnetic moment of the magnet in degrees from the z
        axis. Defaults to 0 degrees clockwise from Z axis (i.e. north pole
        points in the +z direction).
    """

    _codes = [Path.MOVETO,
              Path.LINETO,
              Path.LINETO,
              Path.LINETO,
              Path.CLOSEPOLY]

    def __init__(self, r0=1., z0=0., width=0.01, height=0.01, mu_hat=0., **kwargs):
        self.r0 = r0
        self.z0 = z0
        self.width = width
        self.height = height
        self.mu_hat = mu_hat
        weights = kwargs.pop('weights', None)
        if weights is None:
            weights = np.ones(16)
            weights[:8] = -1.
        super().__init__(weights=weights, **kwargs)

    @property
    def r0(self):
        return self._r0

    @property
    def z0(self):
        return self._z0

    @property
    def centroid(self):
        return np.array([self.r0, self.z0])

    @property
    def width(self):
        return self._width

    @property
    def height(self):
        return self._height

    @property
    def mu_hat(self):
        return self._mu_hat

    @property
    def npts(self):
        return len(self._weights)

    @property
    def rz_pts(self):
        # Compute the rz_pts locations from this coil's internal parameters
        npts = self.npts
        hnpts = npts//2
        r0, z0 = self.centroid
        hw, hh = self.width/2, self.height/2
        rspace, zspace = hw*np.ones(hnpts), np.linspace(-hh, hh, hnpts)

        rz_pts = np.empty((npts, 2))
        rz_pts[0:hnpts, 0] = r0 - rspace
        rz_pts[hnpts:, 0] = r0 + rspace
        rz_pts[0:hnpts, 1] = z0 + zspace
        rz_pts[hnpts:, 1] = z0 + zspace

        if np.isclose(self.mu_hat, 0, rtol=0., atol=cv._ATOL):
            return rz_pts
        return rotate(rz_pts, self.mu_hat, pivot=(r0, z0))

    @property
    def _verts(self):
        # Get indices for 4 corners of current filament array
        npts = self.npts
        idx = np.array([0, npts//2 - 1, npts - 1, npts//2, 0])
        return self.rz_pts[idx, :]

    @property
    def patch(self):
        return patches.PathPatch(Path(self._verts, self._codes), **self.patch_kw)

    @r0.setter
    @cv.flag_greens_on_set
    def r0(self, r0):
        self._r0 = r0

    @z0.setter
    @cv.flag_greens_on_set
    def z0(self, z0):
        self._z0 = z0

    @centroid.setter
    @cv.flag_greens_on_set
    def centroid(self, centroid):
        self._r0 = centroid[0]
        self._z0 = centroid[1]

    @width.setter
    @cv.flag_greens_on_set
    def width(self, width):
        self._width = width

    @height.setter
    @cv.flag_greens_on_set
    def height(self, height):
        self._height = height

    @mu_hat.setter
    @cv.flag_greens_on_set
    def mu_hat(self, mu_hat):
        self._mu_hat = mu_hat

    def translate(self, vector):
        self.centroid += np.array(vector)

    def rotate(self, angle, pivot=(0., 0.)):
        self.mu_hat += angle
        angle = math.pi*angle / 180
        c, s = np.cos(angle), np.sin(angle)
        rotation = np.array([[c, -s], [s, c]])
        self.centroid = (self.centroid - pivot) @ rotation + np.asarray(pivot)
