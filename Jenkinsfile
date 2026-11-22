pipeline {
    agent any

    options {
        skipDefaultCheckout(true)
        disableConcurrentBuilds()
        timeout(time: 30, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    parameters {
        string(name: 'EXPECTED_REVISION', defaultValue: '', description: 'Full main commit SHA. Required for server staging.')
        booleanParam(name: 'STAGE_ON_SOURCE', defaultValue: false, description: 'Upload and prepare the release without activating it.')
    }

    stages {
        stage('Checkout') {
            steps {
                deleteDir()
                script {
                    def source = checkout scm
                    env.RELEASE_REVISION = sh(script: 'git rev-parse HEAD', returnStdout: true).trim()
                    def expected = params.EXPECTED_REVISION.trim()
                    if (expected && expected != env.RELEASE_REVISION) {
                        error('The checked-out commit differs from EXPECTED_REVISION.')
                    }
                    if (params.STAGE_ON_SOURCE && (!expected || source.GIT_BRANCH != 'origin/main')) {
                        error('Server staging requires an explicit SHA and a checkout of origin/main.')
                    }
                }
            }
        }

        stage('Validate deployment assets') {
            steps {
                sh '''
                    set -eu
                    config=scripts/deploy/config/.env.deploy.example
                    for output in upstream units; do
                        python3 scripts/deploy/render-runtime.py "$config" "$output" > /dev/null
                    done
                    python3 scripts/deploy/render-runtime.py "$config" sudoers --deploy-user deploy > /dev/null
                    for script in scripts/deploy/*.sh; do
                        bash -n "$script"
                    done
                '''
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

        stage('Stage on source server') {
            when {
                expression { params.STAGE_ON_SOURCE }
            }
            steps {
                sshagent(credentials: ['project1-v2-deploy']) {
                    sh 'bash scripts/deploy/upload-release.sh "release-artifacts/${RELEASE_REVISION}-${BUILD_NUMBER}"'
                }
            }
        }
    }
}
