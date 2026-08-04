const gulp = require('gulp');

function buildIcons() {
	return gulp.src('nodes/**/*.svg')
		.pipe(gulp.dest('dist/nodes'));
}

exports.default = gulp.series(buildIcons);
