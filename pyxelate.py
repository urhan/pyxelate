import numpy as np
import warnings

from skimage.color.adapt_rgb import adapt_rgb, each_channel
from skimage.util import view_as_blocks
from skimage.morphology import square
from skimage.filters import median
from skimage.color import rgb2hsv, hsv2rgb
from skimage.exposure import equalize_adapthist
from skimage.transform import resize

from sklearn.mixture import BayesianGaussianMixture
from sklearn.exceptions import ConvergenceWarning

__version__ = '1.1.2'
__version_info__ = tuple(int(num) for num in __version__.split('.'))

class Pyxelate:

	CONVOLUTIONS = np.array([
		[[2, 2], [2, 2]],

		[[11, -1], [-1, -1]],
		[[-1, 11], [-1, -1]],
		[[-1, -1], [11, -1]],
		[[-1, -1], [-1, 11]],

		[[5, 5], [-1, -1]],
		[[-1, -1], [5, 5]],

		[[5, -1], [5, -1]],
		[[-1, 5], [-1, 5]],

		[[5, -1], [-1, 5]],
		[[-1, 5], [5, -1]],

		[[-1, 3], [3, 3]],
		[[3, -1], [3, 3]],
		[[3, 3], [-1, 3]],
		[[3, 3], [3, -1]]
	], dtype="int")

	SOLUTIONS = np.array([
		[[1, 1], [1, 1]],

		[[0, 1], [1, 1]],
		[[1, 0], [1, 1]],
		[[1, 1], [0, 1]],
		[[1, 1], [1, 0]],

		[[1, 1], [0, 0]],
		[[0, 0], [1, 1]],

		[[1, 0], [1, 0]],
		[[0, 1], [0, 1]],

		[[1, 0], [1, 0]],
		[[0, 1], [0, 1]],

		[[1, 0], [0, 0]],
		[[0, 1], [0, 0]],
		[[0, 0], [1, 0]],
		[[0, 0], [0, 1]],
	], dtype="bool")

	ITER = 2

	def __init__(self, height, width, color=8, dither=True, regenerate_palette=True, random_state=0):
		"""Create instance for generating similar pixel arts."""

		self.height = int(height)
		self.width = int(width)
		if self.width < 1 or self.height < 1:
			raise ValueError("Result can not be smaller than 1x1 pixels.")
		self.color = int(color)
		if self.color < 2:
			raise ValueError("The minimum number of colors is 2.")
		elif self.color > 32:
			raise ValueError("The maximum number of colors is 32.")
		if dither:
			self.dither = 1 / (self.color + 1)
		else:
			self.dither = 0.
		self.regenerate_palette = bool(regenerate_palette)

		# BGM
		self.is_fitted = False
		self.random_state = int(random_state)
		self.model = BayesianGaussianMixture(n_components=self.color,
											 max_iter=256,
											 covariance_type="tied",
											 weight_concentration_prior_type="dirichlet_distribution",
											 mean_precision_prior=1. / 256.,
											 warm_start=False,
											 random_state=self.random_state)

	def convert(self, image):
		"""Generate pixel art from image"""
		# apply adaptive contrast
		image = equalize_adapthist(image) * 255 * 1.14
		image[image <= 8.] = 0.

		# create sample for finding palette
		if self.regenerate_palette or not self.is_fitted:
			examples = resize(image, (32, 32), anti_aliasing=False).reshape(-1, 3).astype("int")
			# suppress warnings from sklearn
			converge = True
			with warnings.catch_warnings(record=True) as w:
				# fit model
				self.model.fit(examples)
				if w and w[-1].category == ConvergenceWarning:
					warnings.filterwarnings('ignore', category=ConvergenceWarning)
					converge = False
			if not converge:
				warnings.warn("The model has failed to converge, try a different number of colors for better results!", Warning)
			self.is_fitted = True

		# resize image to 4 times the desired width and height
		image = resize(image, (self.height * self.ITER * 2, self.width * self.ITER * 2), anti_aliasing=True)
		# generate pixelated image with desired width / height
		image = self._reduce(image)

		# apply palette
		height, width, depth = image.shape
		reshaped = np.reshape(image, (height * width, depth))
		probs = self.model.predict_proba(reshaped)
		y = np.argmax(probs, axis=1)

		# increase hue and snap color values to multiples of 8
		palette = rgb2hsv(self.model.means_.reshape(-1, 1, 3))
		palette[:, :, 1] *= 1.14
		palette = hsv2rgb(palette).reshape(self.color, 3) // 8 * 8
		# generate recolored image
		image = palette[y]

		# apply dither over threshold if it's not zero
		if self.dither:
			# get second best probability by removing the best one
			probs[np.arange(len(y)), y] = 0
			# get new best and values
			v = np.max(probs, axis=1)
			y = np.argmax(probs, axis=1)

			# replace every second pixel with second best color
			pad = not bool(width % 2)
			for i in range(0, len(image), 2):
				if pad:
					# make sure to alternate between starting positions
					i += (i // width) % 2
				if v[i] > self.dither:
					image[i] = palette[y[i]]

		image = np.reshape(image, (height, width, depth))
		return np.clip(image.astype("int"), 0, 255)

	def _reduce(self, image):
		"""Apply convolutions on image ITER times and generate a smaller image
		based on the highest magnitude of gradients"""

		# self is visible to decorated function
		@adapt_rgb(each_channel)
		def _wrapper(dim):
			# apply median filter for noise reduction
			dim = median(dim, square(4))
			for i in range(self.ITER):
				h, w = dim.shape
				h, w = h // 2, w // 2
				new_image = np.zeros((h * w)).astype("int")
				view = view_as_blocks(dim, (2, 2))
				flatten = view.reshape(-1, 2, 2)
				for i, f in enumerate(flatten):
					conv = np.abs(np.sum(np.multiply(self.CONVOLUTIONS, f.reshape(-1, 2, 2)).reshape(-1, 4), axis=1))
					new_image[i] = np.mean(f[self.SOLUTIONS[np.argmax(conv)]])
				new_image = new_image.reshape((h, w))
				dim = new_image.copy()
			return new_image

		return _wrapper(image)
