pipeline {
    agent any

    options {
        skipDefaultCheckout(true)
        disableConcurrentBuilds()
        timeout(time: 30, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    stages {
        stage('Checkout') {
            steps {
                deleteDir()
                checkout scm
            }
        }

        stage('Build and package') {
            steps {
                sh 'bash scripts/deploy/build-release.sh release-artifacts "$BUILD_NUMBER"'
                archiveArtifacts(
                    artifacts: 'release-artifacts/*/*.tar.gz,release-artifacts/*/SHA256SUMS',
                    fingerprint: true,
                    allowEmptyArchive: false
                )
            }
        }
    }
}
